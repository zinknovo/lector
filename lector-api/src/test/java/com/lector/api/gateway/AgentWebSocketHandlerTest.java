package com.lector.api.gateway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.lector.api.config.AgentProperties;
import java.net.URI;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.springframework.web.reactive.socket.HandshakeInfo;
import org.springframework.web.reactive.socket.WebSocketHandler;
import org.springframework.web.reactive.socket.WebSocketMessage;
import org.springframework.web.reactive.socket.WebSocketSession;
import org.springframework.web.reactive.socket.client.WebSocketClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

class AgentWebSocketHandlerTest {
    @Test
    void rejectsPathsWithMoreThanOneSegment() {
        WebSocketClient client = mock(WebSocketClient.class);
        WebSocketSession downstream = session("/ws/extra/thread");
        when(downstream.close()).thenReturn(Mono.empty());
        AgentWebSocketHandler handler = new AgentWebSocketHandler(
            new AgentProperties("http://agent", "ws://agent"), client);

        handler.handle(downstream).block();

        verify(downstream).close();
        verify(client, never()).execute(any(URI.class), any(WebSocketHandler.class));
    }

    @Test
    void relaysTextAndClosesBothSidesWhenEitherDirectionCompletes() {
        AtomicReference<URI> target = new AtomicReference<>();
        AtomicBoolean cancelled = new AtomicBoolean();
        WebSocketMessage request = message("request");
        WebSocketMessage reply = message("reply");
        WebSocketSession downstream = session("/ws/thread-1");
        WebSocketSession upstream = session("/ws/thread-1");
        when(downstream.receive()).thenReturn(
            Flux.just(request).concatWith(Flux.never()).doOnCancel(() -> cancelled.set(true)));
        when(upstream.receive()).thenReturn(Flux.just(reply));
        when(upstream.textMessage("request")).thenReturn(request);
        when(downstream.textMessage("reply")).thenReturn(reply);
        when(upstream.send(any())).thenAnswer(invocation ->
            ((Flux<?>) invocation.getArgument(0)).then());
        when(downstream.send(any())).thenAnswer(invocation ->
            ((Flux<?>) invocation.getArgument(0)).then());
        when(upstream.close()).thenReturn(Mono.empty());
        when(downstream.close()).thenReturn(Mono.empty());
        WebSocketClient client = mock(WebSocketClient.class);
        when(client.execute(any(URI.class), any(WebSocketHandler.class)))
            .thenAnswer(invocation -> {
                target.set(invocation.getArgument(0));
                WebSocketHandler webSocketHandler = invocation.getArgument(1);
                return webSocketHandler.handle(upstream);
            });
        AgentWebSocketHandler handler = new AgentWebSocketHandler(
            new AgentProperties("http://agent", "ws://agent"), client);

        handler.handle(downstream).block();

        assertEquals(URI.create("ws://agent/ws/thread-1"), target.get());
        org.junit.jupiter.api.Assertions.assertTrue(cancelled.get());
        verify(upstream).close();
        verify(downstream).close();
    }

    @Test
    void closesBothSidesWhenRelayFails() {
        WebSocketSession downstream = session("/ws/thread-1");
        WebSocketSession upstream = session("/ws/thread-1");
        when(downstream.receive()).thenReturn(Flux.never());
        when(upstream.receive()).thenReturn(Flux.error(new IllegalStateException("upstream")));
        when(upstream.send(any())).thenReturn(Mono.never());
        when(downstream.send(any())).thenAnswer(invocation ->
            ((Flux<?>) invocation.getArgument(0)).then());
        when(upstream.close()).thenReturn(Mono.empty());
        when(downstream.close()).thenReturn(Mono.empty());
        WebSocketClient client = mock(WebSocketClient.class);
        when(client.execute(any(URI.class), any(WebSocketHandler.class)))
            .thenAnswer(invocation -> {
                WebSocketHandler webSocketHandler = invocation.getArgument(1);
                return webSocketHandler.handle(upstream);
            });
        AgentWebSocketHandler handler = new AgentWebSocketHandler(
            new AgentProperties("http://agent", "ws://agent"), client);

        assertThrows(IllegalStateException.class, () -> handler.handle(downstream).block());

        verify(upstream).close();
        verify(downstream).close();
    }

    private static WebSocketSession session(String path) {
        WebSocketSession session = mock(WebSocketSession.class);
        HandshakeInfo info = mock(HandshakeInfo.class);
        when(info.getUri()).thenReturn(URI.create("ws://localhost" + path));
        when(session.getHandshakeInfo()).thenReturn(info);
        return session;
    }

    private static WebSocketMessage message(String text) {
        WebSocketMessage message = mock(WebSocketMessage.class);
        when(message.getPayloadAsText()).thenReturn(text);
        return message;
    }
}
