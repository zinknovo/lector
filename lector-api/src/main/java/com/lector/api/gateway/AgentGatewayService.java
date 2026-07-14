package com.lector.api.gateway;

import com.lector.api.config.AgentProperties;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.http.codec.multipart.FilePart;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

@Service
public class AgentGatewayService {
    private final WebClient client;

    public AgentGatewayService(WebClient.Builder builder, AgentProperties properties) {
        this.client = builder.baseUrl(properties.baseUrl()).build();
    }

    public Mono<ResponseEntity<Flux<DataBuffer>>> postJson(String path, Object body) {
        return proxy(client.post().uri(path).bodyValue(body));
    }

    public Mono<ResponseEntity<Flux<DataBuffer>>> post(String path) {
        return proxy(client.post().uri(path));
    }

    public Mono<ResponseEntity<Flux<DataBuffer>>> get(String path) {
        return proxy(client.get().uri(path));
    }

    public Mono<ResponseEntity<Flux<DataBuffer>>> upload(String threadId, FilePart file) {
        MultipartBodyBuilder parts = new MultipartBodyBuilder();
        parts.asyncPart("file", file.content(), org.springframework.core.io.buffer.DataBuffer.class)
            .filename(file.filename())
            .headers(headers -> headers.setContentType(file.headers().getContentType()));
        return proxy(client.post()
            .uri(uri -> uri.path("/api/upload").queryParam("thread_id", threadId).build())
            .body(BodyInserters.fromMultipartData(parts.build())));
    }

    private Mono<ResponseEntity<Flux<DataBuffer>>> proxy(
        WebClient.RequestHeadersSpec<?> request) {
        return request.retrieve()
            .onStatus(status -> status.isError(), response -> Mono.empty())
            .toEntityFlux(DataBuffer.class)
            .map(response -> {
                HttpHeaders headers = new HttpHeaders();
                response.getHeaders().forEach((name, values) -> {
                    if (!isHopByHop(name)) {
                        headers.put(name, values);
                    }
                });
                return new ResponseEntity<>(
                    response.getBody(), headers, response.getStatusCode());
            });
    }

    private static boolean isHopByHop(String name) {
        return name.equalsIgnoreCase(HttpHeaders.CONNECTION)
            || name.equalsIgnoreCase("Keep-Alive")
            || name.equalsIgnoreCase(HttpHeaders.PROXY_AUTHENTICATE)
            || name.equalsIgnoreCase(HttpHeaders.PROXY_AUTHORIZATION)
            || name.equalsIgnoreCase(HttpHeaders.TE)
            || name.equalsIgnoreCase(HttpHeaders.TRAILER)
            || name.equalsIgnoreCase(HttpHeaders.TRANSFER_ENCODING)
            || name.equalsIgnoreCase(HttpHeaders.UPGRADE);
    }
}
