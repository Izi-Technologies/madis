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
         rtp_control/4, rtp_control/5,
         route_call/4, route_call/5,
         publish_event/5,
         registrations/2, registrations/4,
         cdr/2, cdr/4,
         bans/2, ban_ip/6, unban_ip/3,
         sip_inspect/3,
         presence/2, presence/4, presence_user/3,
         routing_rules/2, create_routing_rule/3, delete_routing_rule/3,
         gateways/2, create_gateway/3,
         dids/2, create_did/3,
         dispatch_sets/2, create_dispatch_set/3,
         cluster/2, config/2, set_config/3,
         charge_authorize/3, charge_deny/3,
         capacity_policies/2, upsert_capacity_policy/3,
         delete_gateway/3, delete_did/3, delete_dispatch_set/3, delete_config/3,
         dialplans/2, create_dialplan/3, delete_dialplan/3,
         ip_auth/2, create_ip_auth/4, delete_ip_auth/3,
         access_control/2, create_access_control/5, delete_access_control/3,
         header_rules/2, create_header_rule/3, delete_header_rule/3,
         billing_events/2, billing_ack/3,
         security_events/2,
         ani_groups/2, create_ani_group/4, delete_ani_group/3,
         active_calls/2,
         create_dispatch_member/6, delete_dispatch_member/3,
         users/2, create_user/4, delete_user/3,
         set_log_level/3, health/2, reload/2,
         identity/4, identity/5,
         set_call_flow/4, set_call_flow/5,
         scheduled_calls/2, schedule_call/3, cancel_scheduled_call/3,
         queues/2, create_queue/3, add_queue_member/5, remove_queue_member/4,
         conferences/2, create_conference/3,
         webhooks/2, create_webhook/3, delete_webhook/3,
         tag_call/4,
         number_lookup/3, upsert_number/3,
         routing_intelligence/2, record_routing_outcome/3,
         events/2, events/3, events/4, events/5,
         ws_url/4]).

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

capacity_policies(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/capacity/policies", none).

upsert_capacity_policy(Base, Token, Json) ->
    request(Base, Token, post, "/api/v1/maf/capacity/policies", Json, none).

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

delete_gateway(Base, Token, GatewayId) ->
    request(Base, Token, delete, "/api/v1/maf/gateways/" ++ integer_to_list(GatewayId), none).

delete_did(Base, Token, DidId) ->
    request(Base, Token, delete, "/api/v1/maf/dids/" ++ integer_to_list(DidId), none).

delete_dispatch_set(Base, Token, SetId) ->
    request(Base, Token, delete, "/api/v1/maf/dispatch-sets/" ++ integer_to_list(SetId), none).

delete_config(Base, Token, Key) ->
    request(Base, Token, delete, "/api/v1/maf/config/" ++ uri_string:percent_encode(Key, uri_string:urlchar_reserved()), none).

dialplans(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/dialplans", none).

create_dialplan(Base, Token, Body) ->
    request(Base, Token, post, "/api/v1/maf/dialplans", Body, none).

delete_dialplan(Base, Token, DialplanId) ->
    request(Base, Token, delete, "/api/v1/maf/dialplans/" ++ integer_to_list(DialplanId), none).

ip_auth(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/ip-auth", none).

create_ip_auth(Base, Token, Ip, Description) ->
    Body = jsx:encode(#{<<"ip">> => list_to_binary(Ip), <<"description">> => list_to_binary(Description)}),
    request(Base, Token, post, "/api/v1/maf/ip-auth", Body, none).

delete_ip_auth(Base, Token, IpAuthId) ->
    request(Base, Token, delete, "/api/v1/maf/ip-auth/" ++ integer_to_list(IpAuthId), none).

access_control(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/access-control", none).

create_access_control(Base, Token, Rule, Source, Description) ->
    Body = jsx:encode(#{<<"rule">> => list_to_binary(Rule), <<"source">> => list_to_binary(Source), <<"description">> => list_to_binary(Description)}),
    request(Base, Token, post, "/api/v1/maf/access-control", Body, none).

delete_access_control(Base, Token, AclId) ->
    request(Base, Token, delete, "/api/v1/maf/access-control/" ++ integer_to_list(AclId), none).

header_rules(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/header-rules", none).

create_header_rule(Base, Token, Body) ->
    request(Base, Token, post, "/api/v1/maf/header-rules", Body, none).

delete_header_rule(Base, Token, RuleId) ->
    request(Base, Token, delete, "/api/v1/maf/header-rules/" ++ integer_to_list(RuleId), none).

billing_events(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/billing/events", none).

billing_ack(Base, Token, EventIds) ->
    Body = jsx:encode(#{<<"event_ids">> => [list_to_binary(Id) || Id <- EventIds]}),
    request(Base, Token, post, "/api/v1/maf/billing/events/ack", Body, none).

security_events(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/security/events", none).

ani_groups(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/ani-groups", none).

create_ani_group(Base, Token, Name, Numbers) ->
    Body = jsx:encode(#{<<"name">> => list_to_binary(Name), <<"numbers">> => [list_to_binary(N) || N <- Numbers]}),
    request(Base, Token, post, "/api/v1/maf/ani-groups", Body, none).

delete_ani_group(Base, Token, GroupId) ->
    request(Base, Token, delete, "/api/v1/maf/ani-groups/" ++ integer_to_list(GroupId), none).

active_calls(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/calls/active", none).

create_dispatch_member(Base, Token, DispatchSetId, GatewayId, Weight, Priority) ->
    Body = jsx:encode(#{<<"dispatch_set_id">> => DispatchSetId, <<"gateway_id">> => GatewayId, <<"weight">> => Weight, <<"priority">> => Priority}),
    request(Base, Token, post, "/api/v1/maf/dispatch-members", Body, none).

delete_dispatch_member(Base, Token, MemberId) ->
    request(Base, Token, delete, "/api/v1/maf/dispatch-members/" ++ integer_to_list(MemberId), none).

users(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/users", none).

create_user(Base, Token, Username, Password) ->
    Body = jsx:encode(#{<<"username">> => list_to_binary(Username), <<"password">> => list_to_binary(Password)}),
    request(Base, Token, post, "/api/v1/maf/users", Body, none).

delete_user(Base, Token, UserId) ->
    request(Base, Token, delete, "/api/v1/maf/users/" ++ integer_to_list(UserId), none).

set_log_level(Base, Token, Level) ->
    Body = jsx:encode(#{<<"level">> => list_to_binary(Level)}),
    request(Base, Token, post, "/api/v1/maf/log-level", Body, none).

health(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/health", none).

reload(Base, Token) ->
    request(Base, Token, post, "/api/v1/maf/reload", none, none).

%% --- Call Flows ---

set_call_flow(Base, Token, CallId, Json) ->
    set_call_flow(Base, Token, CallId, Json, none).
set_call_flow(Base, Token, CallId, Json, IdempotencyKey) ->
    Key = idempotency_key(IdempotencyKey),
    request(Base, Token, post, call_path(CallId) ++ "/flow", Json, Key).

%% --- Scheduled Calls ---

scheduled_calls(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/scheduled-calls", none).

schedule_call(Base, Token, Json) ->
    request(Base, Token, post, "/api/v1/maf/scheduled-calls", Json, none).

cancel_scheduled_call(Base, Token, ScheduleId) ->
    request(Base, Token, delete, "/api/v1/maf/scheduled-calls/" ++ integer_to_list(ScheduleId), none).

%% --- Queues ---

queues(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/queues", none).

create_queue(Base, Token, Json) ->
    request(Base, Token, post, "/api/v1/maf/queues", Json, none).

add_queue_member(Base, Token, QueueId, AgentUri, Priority) ->
    Body = jsx:encode(#{<<"agent_uri">> => list_to_binary(AgentUri), <<"priority">> => Priority}),
    request(Base, Token, post, "/api/v1/maf/queues/" ++ integer_to_list(QueueId) ++ "/members", Body, none).

remove_queue_member(Base, Token, QueueId, MemberId) ->
    request(Base, Token, delete, "/api/v1/maf/queues/" ++ integer_to_list(QueueId) ++ "/members/" ++ integer_to_list(MemberId), none).

%% --- Conferences ---

conferences(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/conferences", none).

create_conference(Base, Token, Json) ->
    request(Base, Token, post, "/api/v1/maf/conferences", Json, none).

%% --- Webhooks ---

webhooks(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/webhooks", none).

create_webhook(Base, Token, Json) ->
    request(Base, Token, post, "/api/v1/maf/webhooks", Json, none).

delete_webhook(Base, Token, WebhookId) ->
    request(Base, Token, delete, "/api/v1/maf/webhooks/" ++ integer_to_list(WebhookId), none).

%% --- Call Tags ---

tag_call(Base, Token, CallId, Json) ->
    request(Base, Token, post, call_path(CallId) ++ "/tags", Json, none).

%% --- Number Intelligence ---

number_lookup(Base, Token, Number) ->
    request(Base, Token, get, "/api/v1/maf/number/" ++ uri_string:percent_encode(Number, uri_string:urlchar_reserved()), none).

upsert_number(Base, Token, Json) ->
    request(Base, Token, post, "/api/v1/maf/number", Json, none).

%% --- Routing Intelligence ---

routing_intelligence(Base, Token) ->
    request(Base, Token, get, "/api/v1/maf/routing/intelligence", none).

record_routing_outcome(Base, Token, Json) ->
    request(Base, Token, post, "/api/v1/maf/routing/intelligence/record", Json, none).

identity(Base, Token, CallId, Json) ->
    identity(Base, Token, CallId, Json, none).
identity(Base, Token, CallId, Json, IdempotencyKey) ->
    Key = idempotency_key(IdempotencyKey),
    request(Base, Token, post, call_path(CallId) ++ "/identity", Json, Key).

%% Build the WebSocket URL for direct connection with gun or websocket_client.
ws_url(Base, Cursor, EventType, CallId) ->
    WsBase = re:replace(re:replace(Base, "^https://", "wss://", [{return,list}]),
                        "^http://", "ws://", [{return,list}]),
    Q = "?cursor=" ++ integer_to_list(max(Cursor, 0)),
    TypeQ = case EventType of none -> ""; T -> "&event_type=" ++ T end,
    CallQ = case CallId of none -> ""; C -> "&call_id=" ++ C end,
    WsBase ++ "/api/v1/maf/events/ws" ++ Q ++ TypeQ ++ CallQ.
