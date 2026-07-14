package com.lector.api.security;

import com.lector.api.config.GatewaySecurityProperties;
import io.github.bucket4j.Bucket;
import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 1)
public class RateLimitWebFilter implements WebFilter {
    private final ConcurrentHashMap<String, Bucket> buckets = new ConcurrentHashMap<>();
    private final long capacity;
    private final long refill;

    public RateLimitWebFilter(GatewaySecurityProperties properties) {
        this.capacity = properties.rateCapacity();
        this.refill = properties.rateRefillPerMinute();
    }

    private Bucket newBucket() {
        return Bucket.builder()
            .addLimit(limit -> limit.capacity(capacity)
                .refillGreedy(refill, Duration.ofMinutes(1)))
            .build();
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
        if (exchange.getRequest().getPath().value().equals("/actuator/health")) {
            return chain.filter(exchange);
        }
        String key = exchange.getRequest().getHeaders().getFirst(ApiKeyWebFilter.HEADER);
        if (key == null) {
            return chain.filter(exchange);
        }
        if (!buckets.computeIfAbsent(key, ignored -> newBucket()).tryConsume(1)) {
            exchange.getResponse().setStatusCode(HttpStatus.TOO_MANY_REQUESTS);
            exchange.getResponse().getHeaders().set("Retry-After", "60");
            return exchange.getResponse().setComplete();
        }
        return chain.filter(exchange);
    }
}
