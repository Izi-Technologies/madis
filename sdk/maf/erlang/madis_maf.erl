-module(madis_maf).
-export([create_call/3, create_call/4, get_call/3,
         answer_call/4, answer_call/5,
         reject_call/3, reject_call/4, reject_call/5,
         hangup_call/3, hangup_call/4, hangup_call/5,
         bridge_call/4, bridge_call/5,
         media/4, media/5,
         set_headers/4, set_headers/5,
         transfer_call/4, transfer_call/5,
         hold_call/3, hold_call/4,
         unhold_call/3, unhold_call/4,
         send_dtmf/4, send_dtmf/5,
         events/2, events/3, events/4, events/5]).

-define(MAF_VERSION, "0.7.0").
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

transfer_call(Base, Token, CallId, Json) ->
    transfer_call(Base, Token, CallId, Json, none).
transfer_call(Base, Token, CallId, Json, IdempotencyKey) ->
    Key = idempotency_key(IdempotencyKey),
    request(Base, Token, post, call_path(CallId) ++ "/transfer", Json, Key).

hold_call(Base, Token, CallId) ->
    hold_call(Base, Token, CallId, none).
hold_call(Base, Token, CallId, IdempotencyKey) ->
    Key = idempotency_key(IdempotencyKey),
    request(Base, Token, post, call_path(CallId) ++ "/hold", none, Key).

unhold_call(Base, Token, CallId) ->
    unhold_call(Base, Token, CallId, none).
unhold_call(Base, Token, CallId, IdempotencyKey) ->
    Key = idempotency_key(IdempotencyKey),
    request(Base, Token, post, call_path(CallId) ++ "/unhold", none, Key).

send_dtmf(Base, Token, CallId, Json) ->
    send_dtmf(Base, Token, CallId, Json, none).
send_dtmf(Base, Token, CallId, Json, IdempotencyKey) ->
    Key = idempotency_key(IdempotencyKey),
    request(Base, Token, post, call_path(CallId) ++ "/dtmf", Json, Key).

rtp_control(Base, Token, CallId, Json) ->
    rtp_control(Base, Token, CallId, Json, none).
rtp_control(Base, Token, CallId, Json, IdempotencyKey) ->
    Key = idempotency_key(IdempotencyKey),
    request(Base, Token, post, call_path(CallId) ++ "/rtp", Json, Key).

route_call(Base, Token, CallId, Json) ->
    route_call(Base, Token, CallId, Json, none).
route_call(Base, Token, CallId, Json, IdempotencyKey) ->
    Key = idempotency_key(IdempotencyKey),
    request(Base, Token, post, call_path(CallId) ++ "/route", Json, Key).

publish_event(Base, Token, EventType, CallId, Payload) ->
    Body = case Payload of
        none -> #{<<"event_type">> => list_to_binary(EventType), <<"call_id">> => list_to_binary(CallId)};
        P -> #{<<"event_type">> => list_to_binary(EventType), <<"call_id">> => list_to_binary(CallId), <<"payload">> => list_to_binary(P)}
    end,
    request(Base, Token, post, "/api/v1/maf/events", jsx:encode(Body), none).

registrations(Base, Token) -> registrations(Base, Token, none, 100).
registrations(Base, Token, Aor, Limit) ->
    N = min(max(Limit, 1), 100),
    Q = "?limit=" ++ integer_to_list(N),
    AorQ = case Aor of none -> ""; A -> "&aor=" ++ uri_string:percent_encode(A, uri_string:urlchar_reserved()) end,
    request(Base, Token, get, "/api/v1/maf/registrations" ++ Q ++ AorQ, none).

cdr(Base, Token) -> cdr(Base, Token, none, 50).
cdr(Base, Token, CallId, Limit) ->
    N = min(max(Limit, 1), 100),
    Q = "?limit=" ++ integer_to_list(N),
    CQ = case CallId of none -> ""; C -> "&call_id=" ++ uri_string:percent_encode(C, uri_string:urlchar_reserved()) end,
    request(Base, Token, get, "/api/v1/maf/cdr" ++ Q ++ CQ, none).

bans(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/security/bans", none).

ban_ip(Base, Token, SourceIP, Reason, Permanent, DurationMin) ->
    Perm = case Permanent of true -> <<"true">>; _ -> <<"false">> end,
    Body = jsx:encode(#{<<"source_ip">> => list_to_binary(SourceIP), <<"reason">> => list_to_binary(Reason), <<"permanent">> => Perm, <<"duration_min">> => DurationMin}),
    request(Base, Token, post, "/api/v1/maf/security/bans", Body, none).

unban_ip(Base, Token, SourceIP) ->
    request(Base, Token, delete, "/api/v1/maf/security/bans/" ++ uri_string:percent_encode(SourceIP, uri_string:urlchar_reserved()), none).

sip_inspect(Base, Token, CallId) ->
    request(Base, Token, get, call_path(CallId) ++ "/sip", none).

presence(Base, Token) -> presence(Base, Token, none, 100).
presence(Base, Token, Aor, Limit) ->
    Q = "?limit=" ++ integer_to_list(min(max(Limit,1),500)),
    AQ = case Aor of none -> ""; A -> "&aor=" ++ A end,
    request(Base, Token, get, "/api/v1/maf/presence" ++ Q ++ AQ, none).
presence_user(Base, Token, Aor) ->
    request(Base, Token, get, "/api/v1/maf/presence/" ++ Aor, none).
routing_rules(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/routing/rules", none).
create_routing_rule(Base, Token, Body) ->
    request(Base, Token, post, "/api/v1/maf/routing/rules", Body, none).
delete_routing_rule(Base, Token, Id) ->
    request(Base, Token, delete, "/api/v1/maf/routing/rules/" ++ integer_to_list(Id), none).
gateways(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/gateways", none).
create_gateway(Base, Token, Body) ->
    request(Base, Token, post, "/api/v1/maf/gateways", Body, none).
dids(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/dids", none).
create_did(Base, Token, Body) ->
    request(Base, Token, post, "/api/v1/maf/dids", Body, none).
dispatch_sets(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/dispatch-sets", none).
create_dispatch_set(Base, Token, Body) ->
    request(Base, Token, post, "/api/v1/maf/dispatch-sets", Body, none).
cluster(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/cluster", none).
config(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/config", none).
set_config(Base, Token, Body) ->
    request(Base, Token, post, "/api/v1/maf/config", Body, none).
charge_authorize(Base, Token, CallId) ->
    request(Base, Token, post, call_path(CallId) ++ "/charge", none, none).
charge_deny(Base, Token, CallId) ->
    request(Base, Token, post, call_path(CallId) ++ "/charge-deny", none, none).

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

%% Build the WebSocket URL for direct connection with gun or websocket_client.
ws_url(Base, Cursor, EventType, CallId) ->
    WsBase = re:replace(re:replace(Base, "^https://", "wss://", [{return,list}]),
                        "^http://", "ws://", [{return,list}]),
    Q = "?cursor=" ++ integer_to_list(max(Cursor, 0)),
    TypeQ = case EventType of none -> ""; T -> "&event_type=" ++ T end,
    CallQ = case CallId of none -> ""; C -> "&call_id=" ++ C end,
    WsBase ++ "/api/v1/maf/events/ws" ++ Q ++ TypeQ ++ CallQ.
