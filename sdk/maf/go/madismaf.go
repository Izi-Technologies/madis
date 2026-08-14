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
)

// MAFVersion is the protocol version sent as X-MAF-Version on every request.
const MAFVersion = "0.5.0"

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

func (c *Client) CreateCall(ctx context.Context, from, to string, applicationData any, idem string) (map[string]any, error) {
	body := map[string]any{"from": from, "to": to}
	if applicationData != nil {
		body["application_data"] = applicationData
	}
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
