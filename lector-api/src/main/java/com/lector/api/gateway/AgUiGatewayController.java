package com.lector.api.gateway;

import java.util.Map;
import java.util.regex.Pattern;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

/**
 * AG-UI 远端接口的网关转发：POST + SSE 直通（不缓冲）。
 * 认证与限流由 ApiKeyWebFilter / RateLimitWebFilter 统一处理。
 */
@RestController
@RequestMapping("/ag-ui")
public class AgUiGatewayController {
    private static final Pattern RUN_ID = Pattern.compile("^[A-Za-z0-9_-]{1,128}$");
    private final AgentGatewayService service;

    public AgUiGatewayController(AgentGatewayService service) {
        this.service = service;
    }

    @PostMapping(value = "/run", consumes = MediaType.APPLICATION_JSON_VALUE)
    public Mono<ResponseEntity<Flux<DataBuffer>>> run(
        @RequestBody Map<String, Object> payload) {
        return service.postJson("/ag-ui/run", payload);
    }

    @GetMapping("/runs/{runId}/events")
    public Mono<ResponseEntity<Flux<DataBuffer>>> events(
        @PathVariable String runId,
        @RequestParam(value = "after", defaultValue = "0") int after) {
        requireRunId(runId);
        if (after < 0) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_CONTENT, "invalid after");
        }
        return service.get("/ag-ui/runs/" + runId + "/events?after=" + after);
    }

    @GetMapping("/runs/{runId}")
    public Mono<ResponseEntity<Flux<DataBuffer>>> runInfo(@PathVariable String runId) {
        requireRunId(runId);
        return service.get("/ag-ui/runs/" + runId);
    }

    @PostMapping("/runs/{runId}/cancel")
    public Mono<ResponseEntity<Flux<DataBuffer>>> cancel(@PathVariable String runId) {
        requireRunId(runId);
        return service.post("/ag-ui/runs/" + runId + "/cancel");
    }

    private static void requireRunId(String runId) {
        if (!RUN_ID.matcher(runId).matches()) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_CONTENT, "invalid run_id");
        }
    }
}
