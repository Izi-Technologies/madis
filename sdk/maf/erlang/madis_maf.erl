-module(madis_maf).
-export([create_call/3, create_call/4, get_call/3,
         answer_call/4, answer_call/5,
         reject_call/3, reject_call/4, reject_call/5,
         hangup_call/3, hangup_call/4, hangup_call/5,
         bridge_call/4, bridge_call/5,
         media/4, media/5,
         set_headers/4, set_headers/5,
         events/2, events/3, events/4, events/5]).

-define(MAF_VERSION, "0.5.0").
-define(MAX_BODY, 65536).

validate_token(Token) when is_list(Token), length(Token) >= 16, length(Token) =< 512 -> ok;
validate_token(_) -> exit({madis_maf_invalid_token, "MAF token must be 16..512 characters"}).

idempotency_key(none) ->
    Bytes = crypto:strong_rand_bytes(16),
    lists:flatten([io_lib:format("~2.16.0b", [B]) || <<B>> <= Bytes]);
idempotency_key(Key) -> Key.

request(Base, Token, Method, Path, Body) ->
    request(Base, Token, Method, Path, Body, none).

request(Base, Token, Method, Path, Body, IdempotencyKey) ->
    validate_token(Token),
    application:ensure_all_started(inets),
    application:ensure_all_started(crypto),
    Headers = [{"Authorization", "Bearer " ++ Token},
               {"Accept", "application/json"},
               {"X-MAF-Version", ?MAF_VERSION}],
    IdemHeaders = case IdempotencyKey of
        none -> [];
        K -> [{"Idempotency-Key", K}]
    end,
    ContentHeaders = case Body of
        none -> [];
        Json ->
            true = (byte_size(Json) =< ?MAX_BODY),
            [{"content-type", "application/json"},
             {"content-length", integer_to_list(byte_size(Json))}]
    end,
    AllHeaders = Headers ++ IdemHeaders ++ ContentHeaders,
    Req = case Body of
        none -> {Base ++ Path, AllHeaders};
        Json -> {Base ++ Path, AllHeaders, "application/json", Json}
    end,
    case httpc:request(Method, Req, [{timeout, 5000}], []) of
        {ok, {{_, Code, _}, _, Response}} when Code >= 200, Code < 300 -> Response;
        {ok, {{_, Code, _}, _, _}} -> exit({madis_maf_http_error, Code});
        Error -> exit({madis_maf_transport_error, Error})
    end.

call_path(CallId) ->
    "/api/v1/maf/calls/" ++ uri_string:percent_encode(CallId, uri_string:urlchar_reserved()).

create_call(Base, Token, Json) ->
    create_call(Base, Token, Json, none).
create_call(Base, Token, Json, IdempotencyKey) ->
    Key = idempotency_key(IdempotencyKey),
    request(Base, Token, post, "/api/v1/maf/calls", Json, Key).

get_call(Base, Token, CallId) ->
    request(Base, Token, get, call_path(CallId), none).

answer_call(Base, Token, CallId, Json) ->
    answer_call(Base, Token, CallId, Json, none).
answer_call(Base, Token, CallId, Json, IdempotencyKey) ->
    Key = idempotency_key(IdempotencyKey),
    request(Base, Token, post, call_path(CallId) ++ "/answer", Json, Key).

reject_call(Base, Token, CallId) ->
    reject_call(Base, Token, CallId, none, none).
reject_call(Base, Token, CallId, Json) ->
    reject_call(Base, Token, CallId, Json, none).
reject_call(Base, Token, CallId, Json, IdempotencyKey) ->
    Key = idempotency_key(IdempotencyKey),
    Body = case Json of none -> none; _ -> Json end,
    request(Base, Token, post, call_path(CallId) ++ "/reject", Body, Key).

hangup_call(Base, Token, CallId) ->
    hangup_call(Base, Token, CallId, none, none).
hangup_call(Base, Token, CallId, Json) ->
    hangup_call(Base, Token, CallId, Json, none).
hangup_call(Base, Token, CallId, Json, IdempotencyKey) ->
    Key = idempotency_key(IdempotencyKey),
    Body = case Json of none -> none; _ -> Json end,
    request(Base, Token, post, call_path(CallId) ++ "/hangup", Body, Key).

bridge_call(Base, Token, CallId, Json) ->
    bridge_call(Base, Token, CallId, Json, none).
bridge_call(Base, Token, CallId, Json, IdempotencyKey) ->
    Key = idempotency_key(IdempotencyKey),
    request(Base, Token, post, call_path(CallId) ++ "/bridges", Json, Key).

media(Base, Token, CallId, Json) ->
    media(Base, Token, CallId, Json, none).
media(Base, Token, CallId, Json, IdempotencyKey) ->
    Key = idempotency_key(IdempotencyKey),
    request(Base, Token, post, call_path(CallId) ++ "/media", Json, Key).

set_headers(Base, Token, CallId, Json) ->
    set_headers(Base, Token, CallId, Json, none).
set_headers(Base, Token, CallId, Json, IdempotencyKey) ->
    Key = idempotency_key(IdempotencyKey),
    request(Base, Token, post, call_path(CallId) ++ "/headers", Json, Key).

events(Base, Token) -> events(Base, Token, 0, none, 100).
events(Base, Token, Cursor) -> events(Base, Token, Cursor, none, 100).
events(Base, Token, Cursor, Limit) -> events(Base, Token, Cursor, none, Limit).
events(Base, Token, Cursor, EventType, Limit) ->
    N = min(max(Limit, 1), 100),
    Q = "?cursor=" ++ integer_to_list(max(Cursor, 0)) ++ "&limit=" ++ integer_to_list(N),
    TypeQ = case EventType of
        none -> "";
        T -> "&event_type=" ++ uri_string:percent_encode(T, uri_string:urlchar_reserved())
    end,
    request(Base, Token, get, "/api/v1/maf/events" ++ Q ++ TypeQ, none).
