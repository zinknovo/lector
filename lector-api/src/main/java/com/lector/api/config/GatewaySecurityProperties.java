package com.lector.api.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("lector.security")
public record GatewaySecurityProperties(String apiKey, long rateCapacity, long rateRefillPerMinute) {
    public GatewaySecurityProperties {
        if (apiKey == null || apiKey.isBlank()) {
            throw new IllegalArgumentException("LECTOR_API_KEY must be configured");
        }
        if (rateCapacity < 1 || rateRefillPerMinute < 1) {
            throw new IllegalArgumentException("rate limits must be positive");
        }
    }
}
