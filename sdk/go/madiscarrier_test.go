package madiscarrier

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"
)

type mockRoundTripper func(*http.Request) (*http.Response, error)

func (m mockRoundTripper) RoundTrip(req *http.Request) (*http.Response, error) {
	return m(req)
}

func TestCarrierClientOperations(t *testing.T) {
	var requests []*http.Request
	client := &Client{
		BaseURL: "https://proxy.example.net/admin",
		Token:   "carrier-token-1234567890",
		HTTP: &http.Client{Transport: mockRoundTripper(func(req *http.Request) (*http.Response, error) {
			requests = append(requests, req)
			return &http.Response{
				StatusCode: 200,
				Body:       io.NopCloser(strings.NewReader(`{"ok":true,"count":1}`)),
				Header:     make(http.Header),
			}, nil
		})},
	}
	ctx := context.Background()

	// 1. Basic capabilities & billing
	if _, err := client.Capabilities(ctx); err != nil {
		t.Fatal(err)
	}
	if _, err := client.PendingEvents(ctx, 50); err != nil {
		t.Fatal(err)
	}
	if _, err := client.Publish(ctx, map[string]any{"event_type": "cdr.lifecycle"}); err != nil {
		t.Fatal(err)
	}
	if _, err := client.Ack(ctx, "evt-1234"); err != nil {
		t.Fatal(err)
	}
	if _, err := client.CDR(ctx, 25, "call-1"); err != nil {
		t.Fatal(err)
	}

	// 2. Control status & routing rules
	if _, err := client.ControlStatus(ctx); err != nil {
		t.Fatal(err)
	}
	if _, err := client.RoutingRules(ctx, 100); err != nil {
		t.Fatal(err)
	}
	if _, err := client.CreateRoutingRule(ctx, map[string]any{"action": "gateway", "prefix": "1"}); err != nil {
		t.Fatal(err)
	}
	if _, err := client.SetRoutingRuleEnabled(ctx, 1, true); err != nil {
		t.Fatal(err)
	}
	if _, err := client.SetRoutingRuleEnabled(ctx, 1, false); err != nil {
		t.Fatal(err)
	}

	// 3. Dialplans
	if _, err := client.Dialplans(ctx, 10); err != nil {
		t.Fatal(err)
	}
	if _, err := client.CreateDialplan(ctx, map[string]any{"match": "^9", "strip": 1}); err != nil {
		t.Fatal(err)
	}
	if _, err := client.SetDialplanEnabled(ctx, 2, true); err != nil {
		t.Fatal(err)
	}
	if _, err := client.UpdateDialplan(ctx, 2, map[string]any{"strip": 2}); err != nil {
		t.Fatal(err)
	}
	if _, err := client.DeleteDialplan(ctx, 2); err != nil {
		t.Fatal(err)
	}

	// 4. Generic control resources
	if _, err := client.ControlResources(ctx, "gateways", 50); err != nil {
		t.Fatal(err)
	}
	if _, err := client.CreateControlResource(ctx, "gateways", map[string]any{"name": "gw-1"}); err != nil {
		t.Fatal(err)
	}
	if _, err := client.UpdateControlResource(ctx, "gateways", 5, map[string]any{"port": 5080}); err != nil {
		t.Fatal(err)
	}
	if _, err := client.DeleteControlResource(ctx, "gateways", 5, "rev-1"); err != nil {
		t.Fatal(err)
	}
	if _, err := client.SetControlResourceEnabled(ctx, "gateways", 5, true); err != nil {
		t.Fatal(err)
	}

	// 5. Validations & custom Request
	if _, err := client.ValidateRoutingRule(ctx, map[string]any{"prefix": "44"}); err != nil {
		t.Fatal(err)
	}
	if _, err := client.ValidateDialplan(ctx, map[string]any{"match": "^0"}); err != nil {
		t.Fatal(err)
	}
	if _, err := client.Request(ctx, "GET", "/healthz", nil); err != nil {
		t.Fatal(err)
	}

	if len(requests) != 23 {
		t.Fatalf("expected 23 requests, got %d", len(requests))
	}
	for _, req := range requests {
		if req.Header.Get("Authorization") != "Bearer carrier-token-1234567890" {
			t.Fatal("missing or incorrect authorization header")
		}
	}
}
