package madiscarrier

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
)

type Client struct {
	BaseURL, Token string
	HTTP           *http.Client
}

var controlResources = map[string]bool{
	"gateways": true, "routes": true, "dispatch-sets": true, "dispatch-members": true,
	"dids": true, "header-rules": true, "access-control": true, "security-bans": true,
	"ani-groups": true, "ani-ranges": true, "registrations": true,
	"registration-bindings": true, "cluster-nodes": true, "security-events": true,
}

func resourcePath(resource string) (string, error) {
	if !controlResources[resource] {
		return "", fmt.Errorf("resource is not in the Madis control allowlist")
	}
	return "/api/v1/control/resources/" + resource, nil
}

func (c *Client) request(ctx context.Context, method, path string, value any) (map[string]any, error) {
	var body io.Reader
	if value != nil {
		b, err := json.Marshal(value)
		if err != nil {
			return nil, err
		}
		if len(b) > 65536 {
			return nil, fmt.Errorf("event body exceeds 64 KiB limit")
		}
		body = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.BaseURL+path, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+c.Token)
	req.Header.Set("Accept", "application/json")
	if value != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	h := c.HTTP
	if h == nil {
		h = http.DefaultClient
	}
	res, err := h.Do(req)
	if err != nil {
		return nil, err
	}
	defer res.Body.Close()
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return nil, fmt.Errorf("Madis API %s", res.Status)
	}
	var out map[string]any
	err = json.NewDecoder(res.Body).Decode(&out)
	return out, err
}

func (c *Client) Capabilities(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, http.MethodGet, "/api/v1/capabilities", nil)
}
func (c *Client) PendingEvents(ctx context.Context, limit int) (map[string]any, error) {
	if limit < 1 {
		limit = 1
	}
	if limit > 100 {
		limit = 100
	}
	return c.request(ctx, http.MethodGet, "/api/v1/billing/events?"+url.Values{"limit": {strconv.Itoa(limit)}}.Encode(), nil)
}
func (c *Client) Publish(ctx context.Context, event any) (map[string]any, error) {
	return c.request(ctx, http.MethodPost, "/api/v1/billing/events", event)
}
func (c *Client) Ack(ctx context.Context, eventID string) (map[string]any, error) {
	return c.request(ctx, http.MethodPost, "/api/v1/billing/events/ack?"+url.Values{"event_id": {eventID}}.Encode(), nil)
}
func (c *Client) CDR(ctx context.Context, limit int, callID string) (map[string]any, error) {
	if limit < 1 {
		limit = 1
	}
	if limit > 100 {
		limit = 100
	}
	values := url.Values{"limit": {strconv.Itoa(limit)}}
	if callID != "" {
		values.Set("call_id", callID)
	}
	return c.request(ctx, http.MethodGet, "/api/v1/billing/cdr?"+values.Encode(), nil)
}
func (c *Client) ControlStatus(ctx context.Context) (map[string]any, error) {
	return c.request(ctx, http.MethodGet, "/api/v1/control/status", nil)
}
func (c *Client) RoutingRules(ctx context.Context, limit int) (map[string]any, error) {
	if limit < 1 {
		limit = 1
	}
	if limit > 100 {
		limit = 100
	}
	return c.request(ctx, http.MethodGet, "/api/v1/control/routing-rules?"+url.Values{"limit": {strconv.Itoa(limit)}}.Encode(), nil)
}
func (c *Client) CreateRoutingRule(ctx context.Context, rule any) (map[string]any, error) {
	return c.request(ctx, http.MethodPost, "/api/v1/control/routing-rules", rule)
}
func (c *Client) SetRoutingRuleEnabled(ctx context.Context, ruleID int, enabled bool) (map[string]any, error) {
	state := "disable"
	if enabled {
		state = "enable"
	}
	return c.request(ctx, http.MethodPost, fmt.Sprintf("/api/v1/control/routing-rules/%d/%s", ruleID, state), nil)
}
func (c *Client) Dialplans(ctx context.Context, limit int) (map[string]any, error) {
	if limit < 1 {
		limit = 1
	}
	if limit > 100 {
		limit = 100
	}
	return c.request(ctx, http.MethodGet, "/api/v1/control/dialplans?"+url.Values{"limit": {strconv.Itoa(limit)}}.Encode(), nil)
}
func (c *Client) CreateDialplan(ctx context.Context, rule any) (map[string]any, error) {
	return c.request(ctx, http.MethodPost, "/api/v1/control/dialplans", rule)
}
func (c *Client) SetDialplanEnabled(ctx context.Context, ruleID int, enabled bool) (map[string]any, error) {
	state := "disable"
	if enabled {
		state = "enable"
	}
	return c.request(ctx, http.MethodPost, fmt.Sprintf("/api/v1/control/dialplans/%d/%s", ruleID, state), nil)
}
func (c *Client) UpdateDialplan(ctx context.Context, ruleID int, rule any) (map[string]any, error) {
	return c.request(ctx, http.MethodPut, fmt.Sprintf("/api/v1/control/dialplans/%d", ruleID), rule)
}
func (c *Client) DeleteDialplan(ctx context.Context, ruleID int) (map[string]any, error) {
	return c.request(ctx, http.MethodDelete, fmt.Sprintf("/api/v1/control/dialplans/%d", ruleID), nil)
}

func (c *Client) ControlResources(ctx context.Context, resource string, limit int) (map[string]any, error) {
	path, err := resourcePath(resource)
	if err != nil {
		return nil, err
	}
	if limit < 1 {
		limit = 1
	}
	if limit > 100 {
		limit = 100
	}
	return c.request(ctx, http.MethodGet, path+"?"+url.Values{"limit": {strconv.Itoa(limit)}}.Encode(), nil)
}

func (c *Client) CreateControlResource(ctx context.Context, resource string, document any) (map[string]any, error) {
	path, err := resourcePath(resource)
	if err != nil {
		return nil, err
	}
	return c.request(ctx, http.MethodPost, path, document)
}

func (c *Client) UpdateControlResource(ctx context.Context, resource string, resourceID int, document any) (map[string]any, error) {
	path, err := resourcePath(resource)
	if err != nil {
		return nil, err
	}
	return c.request(ctx, http.MethodPut, fmt.Sprintf("%s/%d", path, resourceID), document)
}

func (c *Client) DeleteControlResource(ctx context.Context, resource string, resourceID int, expectedRevision string) (map[string]any, error) {
	path, err := resourcePath(resource)
	if err != nil {
		return nil, err
	}
	path = fmt.Sprintf("%s/%d", path, resourceID)
	if expectedRevision != "" {
		path += "?" + url.Values{"expected_revision": {expectedRevision}}.Encode()
	}
	return c.request(ctx, http.MethodDelete, path, nil)
}

func (c *Client) SetControlResourceEnabled(ctx context.Context, resource string, resourceID int, enabled bool) (map[string]any, error) {
	path, err := resourcePath(resource)
	if err != nil {
		return nil, err
	}
	state := "disable"
	if enabled {
		state = "enable"
	}
	return c.request(ctx, http.MethodPost, fmt.Sprintf("%s/%d/%s", path, resourceID, state), nil)
}

func (c *Client) ValidateRoutingRule(ctx context.Context, rule any) (map[string]any, error) {
	return c.request(ctx, http.MethodPost, "/api/v1/control/validate/routing-rule", rule)
}

func (c *Client) ValidateDialplan(ctx context.Context, rule any) (map[string]any, error) {
	return c.request(ctx, http.MethodPost, "/api/v1/control/validate/dialplan", rule)
}
