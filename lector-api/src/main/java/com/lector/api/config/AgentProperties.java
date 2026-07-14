package com.lector.api.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("lector.agent")
public record AgentProperties(String baseUrl, String wsBaseUrl) {
    public AgentProperties {
        if (baseUrl == null || baseUrl.isBlank()) {
            baseUrl = "http://127.0.0.1:8000";
        }
        if (wsBaseUrl == null || wsBaseUrl.isBlank()) {
            wsBaseUrl = baseUrl.replaceFirst("^http", "ws");
        }
    }
}
