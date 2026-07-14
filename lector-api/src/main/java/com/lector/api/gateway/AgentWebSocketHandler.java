package com.lector.api.gateway;

import com.lector.api.config.AgentProperties;
import java.net.URI;
import java.util.regex.Pattern;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.socket.WebSocketHandler;
import org.springframework.web.reactive.socket.WebSocketSession;
import org.springframework.web.reactive.socket.client.ReactorNettyWebSocketClient;
import reactor.core.publisher.Mono;

@Component
public class AgentWebSocketHandler implements WebSocketHandler {
    private static final Pattern THREAD_ID = Pattern.compile("^[A-Za-z0-9_-]{1,128}$");
    private final AgentProperties properties;
    private final ReactorNettyWebSocketClient client = new ReactorNettyWebSocketClient();

    public AgentWebSocketHandler(AgentProperties properties) {
        this.properties = properties;
    }

    @Override
    public Mono<Void> handle(WebSocketSession downstream) {
        String path = downstream.getHandshakeInfo().getUri().getPath();
        String threadId = path.substring(path.lastIndexOf('/') + 1);
        if (!THREAD_ID.matcher(threadId).matches()) {
            return downstream.close();
        }
        URI upstreamUri = URI.create(properties.wsBaseUrl() + "/ws/" + threadId);
        return client.execute(upstreamUri, upstream -> Mono.when(
            upstream.send(downstream.receive().map(message ->
                upstream.textMessage(message.getPayloadAsText()))),
            downstream.send(upstream.receive().map(message ->
                downstream.textMessage(message.getPayloadAsText())))
        ));
    }
}
