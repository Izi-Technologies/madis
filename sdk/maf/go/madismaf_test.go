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
		return &http.Response{StatusCode: 202, Body: io.NopCloser(strings.NewReader(`{"status":"accepted","resource_id":"call-12345678"}`)), Header: make(http.Header)}, nil
	})}
	ctx := context.Background()
	if _, err = client.CreateCall(ctx, "sip:a@example.net", "sip:b@example.net", nil, "create-123456"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.GetCall(ctx, "call-12345678"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.Events(ctx, 4, 200, "call.created"); err != nil {
		t.Fatal(err)
	}
	if len(requests) != 3 {
		t.Fatalf("got %d requests", len(requests))
	}
	if requests[0].URL.Path != "/admin/api/v1/maf/calls" {
		t.Fatalf("unexpected create path: %s", requests[0].URL.Path)
	}
	if requests[0].Header.Get("Authorization") != "Bearer 0123456789abcdef" {
		t.Fatal("missing bearer token")
	}
	if requests[0].Header.Get("Idempotency-Key") != "create-123456" {
		t.Fatal("missing idempotency key")
	}
	if requests[2].URL.Query().Get("limit") != "100" {
		t.Fatal("limit was not clamped")
	}
}
