package madiscarrier

import (
	"context"
	"net/http"
	"os"
	"testing"
	"time"
)

func skipIfNoProxy(t *testing.T) (*Client, context.Context) {
	t.Helper()
	url := os.Getenv("MADIS_URL")
	token := os.Getenv("MADIS_TOKEN")
	if url == "" || token == "" {
		t.Skip("MADIS_URL and MADIS_TOKEN required")
	}
	c := &Client{
		BaseURL: url,
		Token:   token,
		HTTP:    &http.Client{Timeout: 5 * time.Second},
	}
	return c, context.Background()
}

func TestHealthz(t *testing.T) {
	c, ctx := skipIfNoProxy(t)
	resp, err := c.Request(ctx, "GET", "/healthz", nil)
	if err != nil {
		t.Fatal(err)
	}
	if resp["ok"] != true {
		t.Fatalf("healthz not ok: %v", resp)
	}
	if _, ok := resp["calls"]; !ok {
		t.Fatal("healthz missing calls")
	}
}

func TestReadyz(t *testing.T) {
	c, ctx := skipIfNoProxy(t)
	resp, err := c.Request(ctx, "GET", "/readyz", nil)
	if err != nil {
		t.Fatal(err)
	}
	if resp["ready"] != true {
		t.Fatalf("not ready: %v", resp)
	}
}

func TestState(t *testing.T) {
	c, ctx := skipIfNoProxy(t)
	resp, err := c.Request(ctx, "GET", "/state", nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"registrations", "calls", "cache"} {
		if _, ok := resp[key]; !ok {
			t.Fatalf("state missing %s", key)
		}
	}
}

func TestReload(t *testing.T) {
	c, ctx := skipIfNoProxy(t)
	resp, err := c.Request(ctx, "POST", "/reload", nil)
	if err != nil {
		t.Fatal(err)
	}
	if resp["reloaded"] != true {
		t.Fatalf("reload failed: %v", resp)
	}
}

func TestUnauthorized(t *testing.T) {
	url := os.Getenv("MADIS_URL")
	if url == "" {
		t.Skip("MADIS_URL required")
	}
	c := &Client{
		BaseURL: url,
		Token:   "wrong-token-value-here1234567890",
		HTTP:    &http.Client{Timeout: 5 * time.Second},
	}
	_, err := c.Request(context.Background(), "GET", "/healthz", nil)
	if err == nil {
		t.Fatal("expected error for wrong token")
	}
}

func TestResourceAllowlist(t *testing.T) {
	if _, err := resourcePath("gateways"); err != nil {
		t.Fatal(err)
	}
	if _, err := resourcePath("users"); err == nil {
		t.Fatal("expected error for disallowed resource")
	}
}
