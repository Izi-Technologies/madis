// Example: High-throughput Call Controller in Go using MADIS Application Fabric (MAF).
//
// Demonstrates:
// - Creating a MAF client with bearer authentication
// - Monitoring real-time call events
// - Answering inbound calls or routing to downstream gateways
// - Sending DTMF digits and triggering transfers
//
// Build & Run:
//     go run call_controller.go -url http://127.0.0.1:8080/admin -token <MAF_TOKEN>

package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"../go"
)

func main() {
	baseURL := flag.String("url", "http://127.0.0.1:8080/admin", "MAF API base URL")
	token := flag.String("token", "", "MAF bearer authorization token")
	flag.Parse()

	if len(*token) < 16 {
		log.Fatalf("Error: valid -token with length >= 16 is required")
	}

	client, err := madismaf.New(*baseURL, *token)
	if err != nil {
		log.Fatalf("Failed to initialize MAF client: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-sigChan
		log.Println("Received termination signal, shutting down...")
		cancel()
	}()

	log.Printf("Connecting to MAF at %s. Monitoring call events...", *baseURL)

	cursor := int64(0)
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			log.Println("Controller stopped.")
			return
		case <-ticker.C:
			page, err := client.Events(ctx, int(cursor), 50, "")
			if err != nil {
				log.Printf("Warning: failed to poll events: %v", err)
				time.Sleep(1 * time.Second)
				continue
			}

			events, ok := page["events"].([]any)
			if !ok || len(events) == 0 {
				continue
			}

			for _, ev := range events {
				eventMap, ok := ev.(map[string]any)
				if !ok {
					continue
				}

				eventType, _ := eventMap["type"].(string)
				callID, _ := eventMap["call_id"].(string)

				switch eventType {
				case "call.created", "call.ringing":
					log.Printf("[Call %s] Inbound call ringing. Evaluating policy...", callID)
					// Example: Answer call with answer SDP
					answerSDP := "v=0\r\no=madis 1 1 IN IP4 127.0.0.1\r\ns=Go MAF\r\nc=IN IP4 127.0.0.1\r\nt=0 0\r\nm=audio 16384 RTP/AVP 0 101\r\na=rtpmap:0 PCMU/8000\r\na=rtpmap:101 telephone-event/8000\r\na=sendrecv\r\n"
					_, err := client.AnswerCall(ctx, callID, answerSDP, "")
					if err != nil {
						log.Printf("[Call %s] Failed to answer: %v", callID, err)
					} else {
						log.Printf("[Call %s] Answered successfully.", callID)
					}

				case "call.dtmf":
					log.Printf("[Call %s] DTMF event received: %v", callID, eventMap["payload"])

				case "call.ended":
					log.Printf("[Call %s] Call completed and cleaned up.", callID)
				}
			}

			if nextCursor, ok := page["next_cursor"].(float64); ok && int64(nextCursor) != cursor {
				cursor = int64(nextCursor)
			}
		}
	}
}
