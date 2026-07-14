package com.lector.api.gateway;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.lector.api.config.AgentProperties;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.core.io.buffer.DataBufferUtils;

class AgentGatewayServiceTest {
    private HttpServer upstream;
    private AgentGatewayService service;
    private final AtomicReference<String> requestBody = new AtomicReference<>();

    @BeforeEach
    void setUp() throws Exception {
        upstream = HttpServer.create(new InetSocketAddress(0), 0);
        upstream.createContext("/api/task", exchange -> {
            requestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] response = "{\"status\":\"started\"}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(202, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        upstream.createContext("/api/files/thread/report.pdf", exchange -> {
            byte[] response = new byte[512 * 1024];
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        upstream.createContext("/api/error", exchange -> {
            byte[] response = "invalid".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(422, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        upstream.start();
        String baseUrl = "http://127.0.0.1:" + upstream.getAddress().getPort();
        service = new AgentGatewayService(
            WebClient.builder(), new AgentProperties(baseUrl, null));
    }

    @AfterEach
    void tearDown() {
        upstream.stop(0);
    }

    @Test
    void forwardsJsonAndPreservesUpstreamStatus() {
        var response = service.postJson("/api/task", java.util.Map.of("query", "earbuds")).block();

        assertEquals(202, response.getStatusCode().value());
        assertEquals("application/json", response.getHeaders().getContentType().toString());
        org.junit.jupiter.api.Assertions.assertTrue(requestBody.get().contains("earbuds"));
        var body = DataBufferUtils.join(response.getBody()).block();
        assertEquals("{\"status\":\"started\"}", body.toString(StandardCharsets.UTF_8));
        DataBufferUtils.release(body);
    }

    @Test
    void streamsFilesLargerThanDefaultWebClientBuffer() {
        var response = service.get("/api/files/thread/report.pdf").block();
        var body = DataBufferUtils.join(response.getBody()).block();

        assertEquals(512 * 1024, body.readableByteCount());
        DataBufferUtils.release(body);
    }

    @Test
    void preservesUpstreamErrorStatusAndBody() {
        var response = service.get("/api/error").block();
        var body = DataBufferUtils.join(response.getBody()).block();

        assertEquals(422, response.getStatusCode().value());
        assertEquals("invalid", body.toString(StandardCharsets.UTF_8));
        DataBufferUtils.release(body);
    }
}
