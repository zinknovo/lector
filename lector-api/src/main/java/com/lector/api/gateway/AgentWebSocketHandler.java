package com.lector.api.gateway;

import com.lector.api.config.AgentProperties;
import java.net.URI;
import java.util.regex.Pattern;
import org.springframework.stereotype.Component;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.reactive.socket.WebSocketHandler;
import org.springframework.web.reactive.socket.WebSocketSession;
import org.springframework.web.reactive.socket.client.ReactorNettyWebSocketClient;
import org.springframework.web.reactive.socket.client.WebSocketClient;
import reactor.core.publisher.Mono;

@Component
public class AgentWebSocketHandler implements WebSocketHandler {
    private static final Pattern THREAD_ID = Pattern.compile("^[A-Za-z0-9_-]{1,128}$");
    private final AgentProperties properties;
    private final WebSocketClient client;

    @Autowired
    public AgentWebSocketHandler(AgentProperties properties) {
        this(properties, new ReactorNettyWebSocketClient());
    }

    AgentWebSocketHandler(AgentProperties properties, WebSocketClient client) {
        this.properties = properties;
        this.client = client;
    }

    @Override
    public Mono<Void> handle(WebSocketSession downstream) {
        String path = downstream.getHandshakeInfo().getUri().getPath();
        String prefix = "/ws/";
        if (!path.startsWith(prefix) || path.indexOf('/', prefix.length()) >= 0) {
            return downstream.close();
        }
        String threadId = path.substring(prefix.length());
        if (!THREAD_ID.matcher(threadId).matches()) {
            return downstream.close();
        }
        URI upstreamUri = URI.create(properties.wsBaseUrl() + "/ws/" + threadId);
        return client.execute(upstreamUri, upstream -> {
            Mono<Void> toUpstream = upstream.send(downstream.receive().map(message ->
                upstream.textMessage(message.getPayloadAsText())));
            Mono<Void> toDownstream = downstream.send(upstream.receive().map(message ->
                downstream.textMessage(message.getPayloadAsText())));
            return Mono.firstWithSignal(toUpstream, toDownstream)
                .then()
                .onErrorResume(error -> closeBoth(upstream, downstream)
                    .then(Mono.error(error)))
                .then(closeBoth(upstream, downstream));
        });
    }

    private static Mono<Void> closeBoth(
        WebSocketSession upstream, WebSocketSession downstream) {
        return Mono.defer(() ->
            Mono.whenDelayError(upstream.close(), downstream.close()));
    }
}
