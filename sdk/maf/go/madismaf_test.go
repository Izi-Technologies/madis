package madismaf

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) { return f(req) }

func TestMAFRoutesAndHeaders(t *testing.T) {
	var requests []*http.Request
	client, err := New("https://proxy.example.net/admin", "0123456789abcdef")
	if err != nil {
		t.Fatal(err)
	}
	client.HTTP = &http.Client{Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
		requests = append(requests, req)
		return &http.Response{
			StatusCode: 202,
			Body:       io.NopCloser(strings.NewReader(`{"status":"accepted","resource_id":"call-12345678"}`)),
			Header:     make(http.Header),
		}, nil
	})}
	ctx := context.Background()

	// 1. Call operations
	if _, err = client.CreateCallWithPresentation(ctx, "sip:a@example.net", "sip:b@example.net", nil, PresentationOptions{CallerID: "+15550001"}, "create-123456"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.GetCall(ctx, "call-12345678"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.AnswerCall(ctx, "call-12345678", "v=0\r\n", "ans-1"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.RejectCall(ctx, "call-12345678", 486, "Busy", "rej-1"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.HangupCall(ctx, "call-12345678", "Normal", "hang-1"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.BridgeCall(ctx, "call-12345678", []string{"ch-1", "ch-2"}, "br-1"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.Media(ctx, "call-12345678", "play", "prompt.wav", "med-1"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.SetHeaders(ctx, "call-12345678", []map[string]any{{"action": "add", "name": "X-Foo", "value": "bar"}}, "hdr-1"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.TransferCall(ctx, "call-12345678", "sip:c@example.net", "blind", "", "xfer-1"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.HoldCall(ctx, "call-12345678", "hold-1"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.UnholdCall(ctx, "call-12345678", "unhold-1"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.SendDTMF(ctx, "call-12345678", "5", 250, "dtmf-1"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.RTPControl(ctx, "call-12345678", "offer", "v=0\r\n", "", "", "", "rtp-1"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.RouteCallWithOptions(ctx, "call-12345678", "sip:agent@10.0.0.1:5060", "udp", "proxy", PresentationOptions{CallerID: "+15559999"}, "route-1"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.Identity(ctx, "call-12345678", "sign", "", "A", "id-1"); err != nil {
		t.Fatal(err)
	}

	// 2. Advanced MAF services
	if _, err = client.ScheduledCalls(ctx); err != nil {
		t.Fatal(err)
	}
	if _, err = client.ScheduleCall(ctx, "sip:a@example.net", "sip:b@example.net", "2026-09-05T12:00:00Z", nil); err != nil {
		t.Fatal(err)
	}
	if _, err = client.CancelScheduledCall(ctx, 1); err != nil {
		t.Fatal(err)
	}
	if _, err = client.Queues(ctx); err != nil {
		t.Fatal(err)
	}
	if _, err = client.CreateQueue(ctx, "support", "round-robin", 180); err != nil {
		t.Fatal(err)
	}
	if _, err = client.AddQueueMember(ctx, 1, "sip:agent@example.net", 1); err != nil {
		t.Fatal(err)
	}
	if _, err = client.RemoveQueueMember(ctx, 1, 10); err != nil {
		t.Fatal(err)
	}
	if _, err = client.Conferences(ctx); err != nil {
		t.Fatal(err)
	}
	if _, err = client.CreateConference(ctx, "conf-1", "1234", 10, true); err != nil {
		t.Fatal(err)
	}
	if _, err = client.Webhooks(ctx); err != nil {
		t.Fatal(err)
	}
	if _, err = client.CreateWebhook(ctx, "https://app.example.net/webhook", []string{"call.answered", "call.dtmf"}, "secret"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.DeleteWebhook(ctx, 1); err != nil {
		t.Fatal(err)
	}
	if _, err = client.TagCall(ctx, "call-12345678", map[string]any{"dept": "sales"}); err != nil {
		t.Fatal(err)
	}
	if _, err = client.NumberLookup(ctx, "+15551234"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.UpsertNumber(ctx, "+15551234", "Verizon", "mobile", "US", 0); err != nil {
		t.Fatal(err)
	}
	if _, err = client.RoutingIntelligence(ctx); err != nil {
		t.Fatal(err)
	}
	if _, err = client.RecordRoutingOutcome(ctx, "gw-1", "+1", true, 60, 450); err != nil {
		t.Fatal(err)
	}

	// 3. Events
	if _, err = client.Events(ctx, 4, 200, "call.created"); err != nil {
		t.Fatal(err)
	}

	if len(requests) != 33 {
		t.Fatalf("got %d requests, expected 33", len(requests))
	}
	if requests[0].URL.Path != "/admin/api/v1/maf/calls" {
		t.Fatalf("unexpected create path: %s", requests[0].URL.Path)
	}
	if requests[0].Header.Get("Authorization") != "Bearer 0123456789abcdef" {
		t.Fatal("missing bearer token")
	}
	if requests[0].Header.Get("X-MAF-Version") != "0.7.0" {
		t.Fatal("missing X-MAF-Version header")
	}
	if requests[0].Header.Get("Idempotency-Key") != "create-123456" {
		t.Fatal("missing idempotency key")
	}
	if requests[32].URL.Query().Get("limit") != "100" {
		t.Fatal("limit was not clamped")
	}

	ws := client.WSUrl(4, "call.dtmf", "call-12345678")
	expectedWS := "wss://proxy.example.net/admin/api/v1/maf/events/ws?call_id=call-12345678&cursor=4&event_type=call.dtmf"
	if ws != expectedWS {
		t.Fatalf("unexpected ws url: %s (expected %s)", ws, expectedWS)
	}
}

