package com.lector.api.security;

import com.lector.api.config.GatewaySecurityProperties;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class ApiKeyWebFilter implements WebFilter {
    public static final String HEADER = "X-API-Key";
    private final byte[] expected;

    public ApiKeyWebFilter(GatewaySecurityProperties properties) {
        this.expected = properties.apiKey().getBytes(StandardCharsets.UTF_8);
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
        if (exchange.getRequest().getPath().value().equals("/actuator/health")) {
            return chain.filter(exchange);
        }
        String supplied = exchange.getRequest().getHeaders().getFirst(HEADER);
        if (supplied == null || !MessageDigest.isEqual(
            expected, supplied.getBytes(StandardCharsets.UTF_8))) {
            exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
            return exchange.getResponse().setComplete();
        }
        return chain.filter(exchange);
    }
}
