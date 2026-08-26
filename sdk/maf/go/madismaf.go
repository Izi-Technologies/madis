// Package madismaf is a small net/http client for the MADIS Application Fabric.
package madismaf

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// MAFVersion is the protocol version sent as X-MAF-Version on every request.
const MAFVersion = "0.7.0"

type Client struct {
	BaseURL string
	Token   string
	HTTP    *http.Client
}

type Error struct {
	Status  int
	Payload any
}

func (e *Error) Error() string {
	return fmt.Sprintf("MAF request failed with HTTP %d: %v", e.Status, e.Payload)
}

func New(baseURL, token string) (*Client, error) {
	if !strings.HasPrefix(baseURL, "http://") && !strings.HasPrefix(baseURL, "https://") {
		return nil, fmt.Errorf("base URL must use HTTP or HTTPS")
	}
	if len(token) < 16 || len(token) > 512 {
		return nil, fmt.Errorf("MAF token must be 16..512 characters")
	}
	return &Client{BaseURL: strings.TrimRight(baseURL, "/"), Token: token, HTTP: http.DefaultClient}, nil
}

func key(value string) string {
	if value != "" {
		return value
	}
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "madis-maf-command"
	}
	return hex.EncodeToString(b)
}

func (c *Client) request(ctx context.Context, method, path string, body any, query url.Values, idem string) (map[string]any, error) {
	if query != nil {
		path += "?" + query.Encode()
	}
	var reader io.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		if len(data) > 65536 {
			return nil, fmt.Errorf("MAF request body exceeds 64 KiB")
		}
		reader = bytes.NewReader(data)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.BaseURL+path, reader)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+c.Token)
	req.Header.Set("Accept", "application/json")
	req.Header.Set("X-MAF-Version", MAFVersion)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if idem != "" {
		req.Header.Set("Idempotency-Key", idem)
	}
	httpClient := c.HTTP
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	res, err := httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer res.Body.Close()
	raw, err := io.ReadAll(res.Body)
	if err != nil {
		return nil, err
	}
	var decoded any
	if len(raw) > 0 && json.Unmarshal(raw, &decoded) != nil {
		decoded = string(raw)
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return nil, &Error{Status: res.StatusCode, Payload: decoded}
	}
	if decoded == nil {
		return map[string]any{}, nil
	}
	value, ok := decoded.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("MAF response is not a JSON object")
	}
	return value, nil
}

func (c *Client) command(ctx context.Context, path string, body map[string]any, idem string) (map[string]any, error) {
	idem = key(idem)
	if body == nil {
		body = map[string]any{}
	}
	if _, ok := body["command_id"]; !ok {
		body["command_id"] = idem
	}
	return c.request(ctx, http.MethodPost, path, body, nil, idem)
}

type PresentationOptions struct {
	CallerURI         string
	CallerID          string
	CallerName        string
	PAssertedIdentity string
	Privacy           string
}

func applyPresentation(body map[string]any, opts PresentationOptions) {
	if opts.CallerURI != "" {
		body["caller_uri"] = opts.CallerURI
	}
	if opts.CallerID != "" {
		body["caller_id"] = opts.CallerID
	}
	if opts.CallerName != "" {
		body["caller_name"] = opts.CallerName
	}
	if opts.PAssertedIdentity != "" {
		body["p_asserted_identity"] = opts.PAssertedIdentity
	}
	if opts.Privacy != "" {
		body["privacy"] = opts.Privacy
	}
}

func (c *Client) CreateCall(ctx context.Context, from, to string, applicationData any, idem string) (map[string]any, error) {
	return c.CreateCallWithPresentation(ctx, from, to, applicationData, PresentationOptions{}, idem)
}

func (c *Client) CreateCallWithPresentation(ctx context.Context, from, to string, applicationData any, presentation PresentationOptions, idem string) (map[string]any, error) {
	body := map[string]any{"from": from, "to": to}
	if applicationData != nil {
		body["application_data"] = applicationData
	}
	applyPresentation(body, presentation)
	return c.command(ctx, "/api/v1/maf/calls", body, idem)
}

func callPath(callID, suffix string) string {
	return "/api/v1/maf/calls/" + url.PathEscape(callID) + suffix
}
func (c *Client) GetCall(ctx context.Context, callID string) (map[string]any, error) {
	return c.request(ctx, http.MethodGet, callPath(callID, ""), nil, nil, "")
}
func (c *Client) AnswerCall(ctx context.Context, callID, sdp, idem string) (map[string]any, error) {
	return c.command(ctx, callPath(callID, "/answer"), map[string]any{"answer_sdp": sdp}, idem)
}
func (c *Client) RejectCall(ctx context.Context, callID string, code int, reason, idem string) (map[string]any, error) {
	return c.command(ctx, callPath(callID, "/reject"), map[string]any{"sip_code": code, "reason": reason}, idem)
}
func (c *Client) HangupCall(ctx context.Context, callID, reason, idem string) (map[string]any, error) {
	return c.command(ctx, callPath(callID, "/hangup"), map[string]any{"reason": reason}, idem)
}
func (c *Client) BridgeCall(ctx context.Context, callID string, channels []string, idem string) (map[string]any, error) {
	return c.command(ctx, callPath(callID, "/bridges"), map[string]any{"channel_ids": channels}, idem)
}
func (c *Client) Media(ctx context.Context, callID, operation, resource, idem string) (map[string]any, error) {
	return c.command(ctx, callPath(callID, "/media"), map[string]any{"operation": operation, "resource": resource}, idem)
}
func (c *Client) SetHeaders(ctx context.Context, callID string, headers []map[string]any, idem string) (map[string]any, error) {
	return c.command(ctx, callPath(callID, "/headers"), map[string]any{"headers": headers}, idem)
}
func (c *Client) TransferCall(ctx context.Context, callID, target, transferType, otherCallID, idem string) (map[string]any, error) {
	body := map[string]any{"target": target, "type": transferType}
	if otherCallID != "" {
		body["other_call_id"] = otherCallID
	}
	return c.command(ctx, callPath(callID, "/transfer"), body, idem)
}
func (c *Client) HoldCall(ctx context.Context, callID, idem string) (map[string]any, error) {
	return c.command(ctx, callPath(callID, "/hold"), map[string]any{}, idem)
}
func (c *Client) UnholdCall(ctx context.Context, callID, idem string) (map[string]any, error) {
	return c.command(ctx, callPath(callID, "/unhold"), map[string]any{}, idem)
}
func (c *Client) SendDTMF(ctx context.Context, callID, digit string, duration int, idem string) (map[string]any, error) {
	if duration <= 0 {
		duration = 250
	}
	return c.command(ctx, callPath(callID, "/dtmf"), map[string]any{"digit": digit, "duration": duration}, idem)
}
func (c *Client) RTPControl(ctx context.Context, callID, action, sdp, fromTag, toTag, flags, idem string) (map[string]any, error) {
	body := map[string]any{"action": action}
	if sdp != "" {
		body["sdp"] = sdp
	}
	if fromTag != "" {
		body["from_tag"] = fromTag
	}
	if toTag != "" {
		body["to_tag"] = toTag
	}
	if flags != "" {
		body["flags"] = flags
	}
	return c.command(ctx, callPath(callID, "/rtp"), body, idem)
}
func (c *Client) RouteCall(ctx context.Context, callID, target, transport, idem string) (map[string]any, error) {
	return c.RouteCallWithOptions(ctx, callID, target, transport, "", PresentationOptions{}, idem)
}

func (c *Client) RouteCallWithOptions(ctx context.Context, callID, target, transport, mode string, presentation PresentationOptions, idem string) (map[string]any, error) {
	body := map[string]any{"target": target}
	if transport != "" {
		body["transport"] = transport
	}
	if mode != "" {
		body["mode"] = mode
	}
	applyPresentation(body, presentation)
	return c.command(ctx, callPath(callID, "/route"), body, idem)
}
func (c *Client) PublishEvent(ctx context.Context, eventType, callID, payload string) (map[string]any, error) {
	body := map[string]any{"event_type": eventType}
	if callID != "" {
		body["call_id"] = callID
	}
	if payload != "" {
		body["payload"] = payload
	}
	return c.request(ctx, "POST", "/api/v1/maf/events", body, nil, "")
}
func (c *Client) Registrations(ctx context.Context, aor string, limit int) (map[string]any, error) {
	if limit < 1 {
		limit = 1
	}
	if limit > 100 {
		limit = 100
	}
	q := url.Values{"limit": {strconv.Itoa(limit)}}
	if aor != "" {
		q.Set("aor", aor)
	}
	return c.request(ctx, "GET", "/api/v1/maf/registrations", nil, q, "")
}
func (c *Client) CDR(ctx context.Context, callID string, limit int) (map[string]any, error) {
	if limit < 1 {
		limit = 1
	}
	if limit > 100 {
		limit = 100
	}
	q := url.Values{"limit": {strconv.Itoa(limit)}}
	if callID != "" {
		q.Set("call_id", callID)
	}
	return c.request(ctx, "GET", "/api/v1/maf/cdr", nil, q, "")
}
func (c *Client) Bans(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/security/bans", nil, nil, "")
}
func (c *Client) BanIP(ctx context.Context, sourceIP, reason string, permanent bool, durationMin int) (map[string]any, error) {
	perm := "false"
	if permanent {
		perm = "true"
	}
	return c.request(ctx, "POST", "/api/v1/maf/security/bans", map[string]any{"source_ip": sourceIP, "reason": reason, "permanent": perm, "duration_min": durationMin}, nil, "")
}
func (c *Client) UnbanIP(ctx context.Context, sourceIP string) (map[string]any, error) {
	return c.request(ctx, "DELETE", "/api/v1/maf/security/bans/"+url.PathEscape(sourceIP), nil, nil, "")
}
func (c *Client) SIPInspect(ctx context.Context, callID string) (map[string]any, error) {
	return c.request(ctx, "GET", callPath(callID, "/sip"), nil, nil, "")
}
func (c *Client) Presence(ctx context.Context, aor string, limit int) (map[string]any, error) {
	q := url.Values{"limit": {strconv.Itoa(limit)}}
	if aor != "" {
		q.Set("aor", aor)
	}
	return c.request(ctx, "GET", "/api/v1/maf/presence", nil, q, "")
}
func (c *Client) PresenceUser(ctx context.Context, aor string) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/presence/"+url.PathEscape(aor), nil, nil, "")
}
func (c *Client) RoutingRules(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/routing/rules", nil, nil, "")
}
func (c *Client) CreateRoutingRule(ctx context.Context, body map[string]any) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/routing/rules", body, nil, "")
}
func (c *Client) DeleteRoutingRule(ctx context.Context, ruleID string) (map[string]any, error) {
	return c.request(ctx, "DELETE", "/api/v1/maf/routing/rules/"+url.PathEscape(ruleID), nil, nil, "")
}
func (c *Client) Gateways(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/gateways", nil, nil, "")
}
func (c *Client) CreateGateway(ctx context.Context, name, address string, port int, transport string) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/gateways", map[string]any{"name": name, "address": address, "port": port, "transport": transport}, nil, "")
}
func (c *Client) DIDs(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/dids", nil, nil, "")
}
func (c *Client) CreateDID(ctx context.Context, number, destinationUser, description string) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/dids", map[string]any{"number": number, "destination_user": destinationUser, "description": description}, nil, "")
}
func (c *Client) DispatchSets(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/dispatch-sets", nil, nil, "")
}
func (c *Client) CreateDispatchSet(ctx context.Context, name, algorithm string) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/dispatch-sets", map[string]any{"name": name, "algorithm": algorithm}, nil, "")
}
func (c *Client) Cluster(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/cluster", nil, nil, "")
}
func (c *Client) Config(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/config", nil, nil, "")
}
func (c *Client) SetConfig(ctx context.Context, key, value, description string) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/config", map[string]any{"key": key, "value": value, "description": description}, nil, "")
}
func (c *Client) ChargeAuthorize(ctx context.Context, callID string) (map[string]any, error) {
	return c.request(ctx, "POST", callPath(callID, "/charge"), nil, nil, "")
}
func (c *Client) ChargeDeny(ctx context.Context, callID string) (map[string]any, error) {
	return c.request(ctx, "POST", callPath(callID, "/charge-deny"), nil, nil, "")
}
func (c *Client) Events(ctx context.Context, cursor, limit int, eventType string) (map[string]any, error) {
	if cursor < 0 {
		cursor = 0
	}
	if limit < 1 {
		limit = 1
	}
	if limit > 100 {
		limit = 100
	}
	q := url.Values{"cursor": {strconv.Itoa(cursor)}, "limit": {strconv.Itoa(limit)}}
	if eventType != "" {
		q.Set("event_type", eventType)
	}
	return c.request(ctx, http.MethodGet, "/api/v1/maf/events", nil, q, "")
}

// Subscribe polls the /events endpoint and sends each event to the channel.
// Blocks until ctx is cancelled. Uses adaptive backoff (50ms-2s).
func (c *Client) Subscribe(ctx context.Context, cursor int, eventType, callID string, ch chan<- map[string]any) error {
	cur := cursor
	interval := 50 * time.Millisecond
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		q := url.Values{"cursor": {strconv.Itoa(cur)}, "limit": {"100"}}
		if eventType != "" {
			q.Set("event_type", eventType)
		}
		if callID != "" {
			q.Set("call_id", callID)
		}
		page, err := c.request(ctx, "GET", "/api/v1/maf/events", nil, q, "")
		if err != nil {
			interval = 2 * time.Second
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(interval):
			}
			continue
		}
		events, _ := page["events"].([]any)
		if len(events) > 0 {
			interval = 50 * time.Millisecond
			for _, e := range events {
				if evt, ok := e.(map[string]any); ok {
					select {
					case ch <- evt:
					case <-ctx.Done():
						return ctx.Err()
					}
				}
			}
			if next, ok := page["next_cursor"].(string); ok {
				if n, err := strconv.Atoi(next); err == nil && n > cur {
					cur = n
				}
			}
		} else {
			if interval < 2*time.Second {
				interval *= 2
			}
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(interval):
		}
	}
}

// WSUrl builds the WebSocket URL for direct connection with gorilla/websocket or nhooyr.io/websocket.
func (c *Client) WSUrl(cursor int, eventType, callID string) string {
	base := strings.Replace(strings.Replace(c.BaseURL, "https://", "wss://", 1), "http://", "ws://", 1)
	q := url.Values{"cursor": {strconv.Itoa(cursor)}}
	if eventType != "" {
		q.Set("event_type", eventType)
	}
	if callID != "" {
		q.Set("call_id", callID)
	}
	return base + "/api/v1/maf/events/ws?" + q.Encode()
}

func (c *Client) CapacityPolicies(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/capacity/policies", nil, nil, "")
}

func (c *Client) UpsertCapacityPolicy(ctx context.Context, body map[string]any) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/capacity/policies", body, nil, "")
}

func (c *Client) DeleteGateway(ctx context.Context, gatewayID int) (map[string]any, error) {
	return c.request(ctx, "DELETE", fmt.Sprintf("/api/v1/maf/gateways/%d", gatewayID), nil, nil, "")
}
func (c *Client) DeleteDID(ctx context.Context, didID int) (map[string]any, error) {
	return c.request(ctx, "DELETE", fmt.Sprintf("/api/v1/maf/dids/%d", didID), nil, nil, "")
}
func (c *Client) DeleteDispatchSet(ctx context.Context, setID int) (map[string]any, error) {
	return c.request(ctx, "DELETE", fmt.Sprintf("/api/v1/maf/dispatch-sets/%d", setID), nil, nil, "")
}
func (c *Client) DeleteConfig(ctx context.Context, key string) (map[string]any, error) {
	return c.request(ctx, "DELETE", "/api/v1/maf/config/"+url.PathEscape(key), nil, nil, "")
}
func (c *Client) Dialplans(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/dialplans", nil, nil, "")
}
func (c *Client) CreateDialplan(ctx context.Context, body map[string]any) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/dialplans", body, nil, "")
}
func (c *Client) DeleteDialplan(ctx context.Context, dialplanID int) (map[string]any, error) {
	return c.request(ctx, "DELETE", fmt.Sprintf("/api/v1/maf/dialplans/%d", dialplanID), nil, nil, "")
}
func (c *Client) IPAuth(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/ip-auth", nil, nil, "")
}
func (c *Client) CreateIPAuth(ctx context.Context, ip, description string) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/ip-auth", map[string]any{"ip": ip, "description": description}, nil, "")
}
func (c *Client) DeleteIPAuth(ctx context.Context, ipAuthID int) (map[string]any, error) {
	return c.request(ctx, "DELETE", fmt.Sprintf("/api/v1/maf/ip-auth/%d", ipAuthID), nil, nil, "")
}
func (c *Client) AccessControl(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/access-control", nil, nil, "")
}
func (c *Client) CreateAccessControl(ctx context.Context, rule, source, description string) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/access-control", map[string]any{"rule": rule, "source": source, "description": description}, nil, "")
}
func (c *Client) DeleteAccessControl(ctx context.Context, aclID int) (map[string]any, error) {
	return c.request(ctx, "DELETE", fmt.Sprintf("/api/v1/maf/access-control/%d", aclID), nil, nil, "")
}
func (c *Client) HeaderRules(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/header-rules", nil, nil, "")
}
func (c *Client) CreateHeaderRule(ctx context.Context, body map[string]any) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/header-rules", body, nil, "")
}
func (c *Client) DeleteHeaderRule(ctx context.Context, ruleID int) (map[string]any, error) {
	return c.request(ctx, "DELETE", fmt.Sprintf("/api/v1/maf/header-rules/%d", ruleID), nil, nil, "")
}
func (c *Client) BillingEvents(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/billing/events", nil, nil, "")
}
func (c *Client) BillingAck(ctx context.Context, eventIDs []string) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/billing/events/ack", map[string]any{"event_ids": eventIDs}, nil, "")
}
func (c *Client) SecurityEvents(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/security/events", nil, nil, "")
}
func (c *Client) ANIGroups(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/ani-groups", nil, nil, "")
}
func (c *Client) CreateANIGroup(ctx context.Context, name string, numbers []string) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/ani-groups", map[string]any{"name": name, "numbers": numbers}, nil, "")
}
func (c *Client) DeleteANIGroup(ctx context.Context, groupID int) (map[string]any, error) {
	return c.request(ctx, "DELETE", fmt.Sprintf("/api/v1/maf/ani-groups/%d", groupID), nil, nil, "")
}
func (c *Client) ActiveCalls(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/calls/active", nil, nil, "")
}
func (c *Client) CreateDispatchMember(ctx context.Context, dispatchSetID, gatewayID, weight, priority int) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/dispatch-members", map[string]any{"dispatch_set_id": dispatchSetID, "gateway_id": gatewayID, "weight": weight, "priority": priority}, nil, "")
}
func (c *Client) DeleteDispatchMember(ctx context.Context, memberID int) (map[string]any, error) {
	return c.request(ctx, "DELETE", fmt.Sprintf("/api/v1/maf/dispatch-members/%d", memberID), nil, nil, "")
}
func (c *Client) Users(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/users", nil, nil, "")
}
func (c *Client) CreateUser(ctx context.Context, username, password string) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/users", map[string]any{"username": username, "password": password}, nil, "")
}
func (c *Client) DeleteUser(ctx context.Context, userID int) (map[string]any, error) {
	return c.request(ctx, "DELETE", fmt.Sprintf("/api/v1/maf/users/%d", userID), nil, nil, "")
}
func (c *Client) SetLogLevel(ctx context.Context, level string) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/log-level", map[string]any{"level": level}, nil, "")
}
func (c *Client) Health(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/health", nil, nil, "")
}
func (c *Client) Reload(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/reload", nil, nil, "")
}
// --- Call Flows ---

func (c *Client) SetCallFlow(ctx context.Context, callID string, steps []map[string]any, idem string) (map[string]any, error) {
	return c.command(ctx, callPath(callID, "/flow"), map[string]any{"steps": steps}, idem)
}

// --- Scheduled Calls ---

func (c *Client) ScheduledCalls(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/scheduled-calls", nil, nil, "")
}
func (c *Client) ScheduleCall(ctx context.Context, from, to, scheduledAt string, applicationData any) (map[string]any, error) {
	body := map[string]any{"from": from, "to": to, "scheduled_at": scheduledAt}
	if applicationData != nil {
		body["application_data"] = applicationData
	}
	return c.request(ctx, "POST", "/api/v1/maf/scheduled-calls", body, nil, "")
}
func (c *Client) CancelScheduledCall(ctx context.Context, scheduleID int) (map[string]any, error) {
	return c.request(ctx, "DELETE", fmt.Sprintf("/api/v1/maf/scheduled-calls/%d", scheduleID), nil, nil, "")
}

// --- Queues ---

func (c *Client) Queues(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/queues", nil, nil, "")
}
func (c *Client) CreateQueue(ctx context.Context, name, strategy string, maxWaitSec int) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/queues", map[string]any{"name": name, "strategy": strategy, "max_wait_sec": maxWaitSec}, nil, "")
}
func (c *Client) AddQueueMember(ctx context.Context, queueID int, agentURI string, priority int) (map[string]any, error) {
	return c.request(ctx, "POST", fmt.Sprintf("/api/v1/maf/queues/%d/members", queueID), map[string]any{"agent_uri": agentURI, "priority": priority}, nil, "")
}
func (c *Client) RemoveQueueMember(ctx context.Context, queueID, memberID int) (map[string]any, error) {
	return c.request(ctx, "DELETE", fmt.Sprintf("/api/v1/maf/queues/%d/members/%d", queueID, memberID), nil, nil, "")
}

// --- Conferences ---

func (c *Client) Conferences(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, "GET", "/api/v1/maf/conferences", nil, nil, "")
}
func (c *Client) CreateConference(ctx context.Context, name, pin string, maxParticipants int, record bool) (map[string]any, error) {
	return c.request(ctx, "POST", "/api/v1/maf/conferences", map[string]any{"name": name, "pin": pin, "max_participants": maxParticipants, "record": record}, nil, "")
}

func (c *Client) Identity(ctx context.Context, callID, action, identity, attest, idem string) (map[string]any, error) {
	body := map[string]any{"action": action}
	if identity != "" {
		body["identity"] = identity
	}
	if attest != "" {
		body["attest"] = attest
	}
	return c.command(ctx, callPath(callID, "/identity"), body, idem)
}
