package com.lector.api.gateway;

import java.util.Map;
import java.util.regex.Pattern;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.codec.multipart.FilePart;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Flux;

@RestController
@RequestMapping("/api")
public class AgentGatewayController {
    private static final Pattern THREAD_ID = Pattern.compile("^[A-Za-z0-9_-]{1,128}$");
    private static final Pattern FILENAME = Pattern.compile("^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$");
    private final AgentGatewayService service;

    public AgentGatewayController(AgentGatewayService service) {
        this.service = service;
    }

    @PostMapping(value = "/task", consumes = MediaType.APPLICATION_JSON_VALUE)
    public Mono<ResponseEntity<Flux<DataBuffer>>> createTask(
        @RequestBody Map<String, Object> payload) {
        return service.postJson("/api/task", payload);
    }

    @PostMapping("/task/{threadId}/cancel")
    public Mono<ResponseEntity<Flux<DataBuffer>>> cancelTask(@PathVariable String threadId) {
        requireThreadId(threadId);
        return service.post("/api/task/" + threadId + "/cancel");
    }

    @GetMapping("/files/{threadId}/{filename}")
    public Mono<ResponseEntity<Flux<DataBuffer>>> download(
        @PathVariable String threadId, @PathVariable String filename) {
        requireThreadId(threadId);
        if (!FILENAME.matcher(filename).matches()) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_CONTENT, "invalid filename");
        }
        return service.get("/api/files/" + threadId + "/" + filename);
    }

    @PostMapping(value = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Mono<ResponseEntity<Flux<DataBuffer>>> upload(
        @RequestParam("thread_id") String threadId,
        @RequestPart("file") FilePart file) {
        requireThreadId(threadId);
        return service.upload(threadId, file);
    }

    private static void requireThreadId(String threadId) {
        if (!THREAD_ID.matcher(threadId).matches()) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_CONTENT, "invalid thread_id");
        }
    }
}
