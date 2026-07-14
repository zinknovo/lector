package com.lector.api.gateway;

import com.lector.api.config.AgentProperties;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.http.codec.multipart.FilePart;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

@Service
public class AgentGatewayService {
    private final WebClient client;

    public AgentGatewayService(WebClient.Builder builder, AgentProperties properties) {
        this.client = builder.baseUrl(properties.baseUrl()).build();
    }

    public Mono<ResponseEntity<byte[]>> postJson(String path, Object body) {
        return client.post().uri(path).bodyValue(body).exchangeToMono(this::copyResponse);
    }

    public Mono<ResponseEntity<byte[]>> post(String path) {
        return client.post().uri(path).exchangeToMono(this::copyResponse);
    }

    public Mono<ResponseEntity<byte[]>> get(String path) {
        return client.get().uri(path).exchangeToMono(this::copyResponse);
    }

    public Mono<ResponseEntity<byte[]>> upload(String threadId, FilePart file) {
        MultipartBodyBuilder parts = new MultipartBodyBuilder();
        parts.asyncPart("file", file.content(), org.springframework.core.io.buffer.DataBuffer.class)
            .filename(file.filename())
            .headers(headers -> headers.setContentType(file.headers().getContentType()));
        return client.post()
            .uri(uri -> uri.path("/api/upload").queryParam("thread_id", threadId).build())
            .body(BodyInserters.fromMultipartData(parts.build()))
            .exchangeToMono(this::copyResponse);
    }

    private Mono<ResponseEntity<byte[]>> copyResponse(
        org.springframework.web.reactive.function.client.ClientResponse response) {
        return response.bodyToMono(byte[].class).defaultIfEmpty(new byte[0]).map(bytes -> {
            HttpHeaders headers = new HttpHeaders();
            response.headers().asHttpHeaders().forEach((name, values) -> {
                if (!name.equalsIgnoreCase(HttpHeaders.TRANSFER_ENCODING)) {
                    headers.put(name, values);
                }
            });
            return new ResponseEntity<>(bytes, headers, response.statusCode());
        });
    }
}
