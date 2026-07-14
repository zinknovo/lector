package com.lector.api;

import com.lector.api.config.AgentProperties;
import com.lector.api.config.GatewaySecurityProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties({AgentProperties.class, GatewaySecurityProperties.class})
public class LectorApiApplication {
    public static void main(String[] args) {
        SpringApplication.run(LectorApiApplication.class, args);
    }
}
