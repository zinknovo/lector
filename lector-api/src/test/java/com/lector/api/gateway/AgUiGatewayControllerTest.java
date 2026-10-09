package com.lector.api.gateway;

import com.lector.api.config.AgentProperties;
import com.lector.api.config.GatewaySecurityProperties;
import com.lector.api.security.ApiKeyWebFilter;
import com.lector.api.security.RateLimitWebFilter;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.core.io.buffer.DefaultDataBufferFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.test.web.reactive.server.WebTestClient;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

class AgUiGatewayControllerTest {
    static class FakeService extends AgentGatewayService {
        final List<String> paths = new ArrayList<>();

        FakeService() {
            super(WebClient.builder(), new AgentProperties("http://localhost", "ws://localhost"));
        }

        private Mono<ResponseEntity<Flux<DataBuffer>>> respond(String path) {
            paths.add(path);
            DataBuffer buffer = DefaultDataBufferFactory.sharedInstance.wrap(new byte[0]);
            return Mono.just(ResponseEntity.ok(Flux.just(buffer)));
        }

        @Override
        public Mono<ResponseEntity<Flux<DataBuffer>>> postJson(String path, Object body) {
            return respond(path);
        }

        @Override
        public Mono<ResponseEntity<Flux<DataBuffer>>> post(String path) {
            return respond(path);
        }

        @Override
        public Mono<ResponseEntity<Flux<DataBuffer>>> get(String path) {
            return respond(path);
        }
    }

    private FakeService service;
    private WebTestClient client;

    @BeforeEach
    void setUp() {
        service = new FakeService();
        GatewaySecurityProperties properties = new GatewaySecurityProperties("test-key", 20, 20);
        client = WebTestClient.bindToController(new AgUiGatewayController(service))
            .webFilter(new ApiKeyWebFilter(properties))
            .webFilter(new RateLimitWebFilter(properties))
            .build();
    }

    @Test
    void rejectsMissingApiKey() {
        client.post().uri("/ag-ui/run")
            .bodyValue("{\"threadId\":\"t1\"}")
            .exchange()
            .expectStatus().isUnauthorized();
        org.junit.jupiter.api.Assertions.assertEquals(0, service.paths.size());
    }

    @Test
    void proxiesRunRequest() {
        client.post().uri("/ag-ui/run")
            .header(ApiKeyWebFilter.HEADER, "test-key")
            .header("Content-Type", "application/json")
            .bodyValue("{\"threadId\":\"t1\",\"runId\":\"r1\"}")
            .exchange()
            .expectStatus().isOk();
        org.junit.jupiter.api.Assertions.assertEquals(List.of("/ag-ui/run"), service.paths);
    }

    @Test
    void proxiesEventReplayWithCursor() {
        client.get().uri("/ag-ui/runs/r1/events?after=3")
            .header(ApiKeyWebFilter.HEADER, "test-key")
            .exchange()
            .expectStatus().isOk();
        org.junit.jupiter.api.Assertions.assertEquals(
            List.of("/ag-ui/runs/r1/events?after=3"), service.paths);
    }

    @Test
    void proxiesCancel() {
        client.post().uri("/ag-ui/runs/r1/cancel")
            .header(ApiKeyWebFilter.HEADER, "test-key")
            .exchange()
            .expectStatus().isOk();
        org.junit.jupiter.api.Assertions.assertEquals(
            List.of("/ag-ui/runs/r1/cancel"), service.paths);
    }

    @Test
    void rejectsInvalidRunIdBeforeProxying() {
        client.post().uri("/ag-ui/runs/bad%20id/cancel")
            .header(ApiKeyWebFilter.HEADER, "test-key")
            .exchange()
            .expectStatus().is4xxClientError();
        org.junit.jupiter.api.Assertions.assertEquals(0, service.paths.size());
    }

    @Test
    void rejectsNegativeCursor() {
        client.get().uri("/ag-ui/runs/r1/events?after=-1")
            .header(ApiKeyWebFilter.HEADER, "test-key")
            .exchange()
            .expectStatus().is4xxClientError();
        org.junit.jupiter.api.Assertions.assertEquals(0, service.paths.size());
    }
}
