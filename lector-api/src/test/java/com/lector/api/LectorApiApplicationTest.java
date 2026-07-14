package com.lector.api;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.web.reactive.server.WebTestClient;

@SpringBootTest(
    webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
    properties = {
        "lector.security.api-key=context-test-key",
        "lector.security.rate-capacity=10",
        "lector.security.rate-refill-per-minute=10",
        "lector.agent.base-url=http://127.0.0.1:1",
        "lector.agent.ws-base-url=ws://127.0.0.1:1"
    })
class LectorApiApplicationTest {
    @LocalServerPort
    int port;

    @Test
    void deployedFilterChainKeepsHealthPublicAndProtectsMetrics() {
        WebTestClient client = WebTestClient.bindToServer()
            .baseUrl("http://127.0.0.1:" + port)
            .build();

        client.get().uri("/actuator/health")
            .exchange()
            .expectStatus().isOk();
        client.get().uri("/actuator/prometheus")
            .exchange()
            .expectStatus().isUnauthorized();
        client.get().uri("/actuator/prometheus")
            .header("X-API-Key", "wrong-key")
            .exchange()
            .expectStatus().isUnauthorized();
    }
}
