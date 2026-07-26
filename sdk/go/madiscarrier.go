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
