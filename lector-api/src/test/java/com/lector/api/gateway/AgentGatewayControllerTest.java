package com.lector.api.gateway;

import com.lector.api.config.AgentProperties;
import com.lector.api.config.GatewaySecurityProperties;
import com.lector.api.security.ApiKeyWebFilter;
import com.lector.api.security.RateLimitWebFilter;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.core.io.buffer.DefaultDataBufferFactory;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.test.web.reactive.server.WebTestClient;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Flux;

class AgentGatewayControllerTest {
    static class FakeService extends AgentGatewayService {
        final AtomicInteger calls = new AtomicInteger();
        byte[] response = new byte[0];

        FakeService() {
            super(WebClient.builder(), new AgentProperties("http://localhost", "ws://localhost"));
        }

        @Override
        public Mono<ResponseEntity<Flux<DataBuffer>>> postJson(String path, Object body) {
            calls.incrementAndGet();
            DataBuffer buffer = DefaultDataBufferFactory.sharedInstance.wrap(response);
            return Mono.just(ResponseEntity.ok(Flux.just(buffer)));
        }

        @Override
        public Mono<ResponseEntity<Flux<DataBuffer>>> get(String path) {
            calls.incrementAndGet();
            DataBuffer buffer = DefaultDataBufferFactory.sharedInstance.wrap(response);
            return Mono.just(ResponseEntity.ok(Flux.just(buffer)));
        }
    }

    private FakeService service;
    private WebTestClient client;

    @RestController
    static class HealthController {
        @GetMapping("/actuator/health")
        Mono<String> health() {
            return Mono.just("UP");
        }
    }

    @BeforeEach
    void setUp() {
        service = new FakeService();
        GatewaySecurityProperties properties = new GatewaySecurityProperties("test-key", 2, 1);
        client = WebTestClient.bindToController(
                new AgentGatewayController(service), new HealthController())
            .webFilter(new ApiKeyWebFilter(properties))
            .webFilter(new RateLimitWebFilter(properties))
            .build();
    }

    @Test
    void rejectsMissingApiKey() {
        client.post().uri("/api/task")
            .bodyValue("{\"query\":\"test\"}")
            .exchange()
            .expectStatus().isUnauthorized();
        org.junit.jupiter.api.Assertions.assertEquals(0, service.calls.get());
    }

    @Test
    void proxiesValidTaskRequest() {
        byte[] response = "{\"status\":\"started\",\"thread_id\":\"t1\"}"
            .getBytes(StandardCharsets.UTF_8);
        service.response = response;

        client.post().uri("/api/task")
            .header(ApiKeyWebFilter.HEADER, "test-key")
            .header("Content-Type", "application/json")
            .bodyValue("{\"query\":\"test\"}")
            .exchange()
            .expectStatus().isOk()
            .expectBody().json("{\"status\":\"started\",\"thread_id\":\"t1\"}");
    }

    @Test
    void rateLimitsRequestsPerKey() {
        for (int index = 0; index < 2; index++) {
            client.post().uri("/api/task")
                .header(ApiKeyWebFilter.HEADER, "test-key")
                .header("Content-Type", "application/json")
                .bodyValue("{\"query\":\"test\"}")
                .exchange().expectStatus().isOk();
        }
        client.post().uri("/api/task")
            .header(ApiKeyWebFilter.HEADER, "test-key")
            .header("Content-Type", "application/json")
            .bodyValue("{\"query\":\"test\"}")
            .exchange()
            .expectStatus().isEqualTo(429)
            .expectHeader().valueEquals("Retry-After", "60");
    }

    @Test
    void rejectsUnsafeFileNameBeforeProxying() {
        client.get().uri("/api/files/thread-1/%2E%2E%2Fsecret")
            .header(ApiKeyWebFilter.HEADER, "test-key")
            .exchange()
            .expectStatus().is4xxClientError();
        org.junit.jupiter.api.Assertions.assertEquals(0, service.calls.get());
    }

    @Test
    void healthIsPublic() {
        client.get().uri("/actuator/health")
            .exchange()
            .expectStatus().isOk()
            .expectBody(String.class).isEqualTo("UP");
    }
}
