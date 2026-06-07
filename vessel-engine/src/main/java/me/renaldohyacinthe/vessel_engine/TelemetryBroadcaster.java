package me.renaldohyacinthe.vessel_engine;

import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class TelemetryBroadcaster {

    private final SimpMessagingTemplate messagingTemplate;
    private final DashboardController dashboardController;

    public TelemetryBroadcaster(SimpMessagingTemplate messagingTemplate, DashboardController dashboardController) {
        this.messagingTemplate = messagingTemplate;
        this.dashboardController = dashboardController;
    }

@Scheduled(fixedRate = 2000)
    public void broadcastClusterState() {
        long startTime = System.currentTimeMillis();
        
        List<Map<String, Object>> shardData = dashboardController.getClusterState();
        
        long actualLatency = System.currentTimeMillis() - startTime;
        long activeNodes = shardData.stream().filter(s -> "UP".equals(s.get("status"))).count();
        
        long totalRecords = shardData.stream()
                .mapToLong(s -> s.get("total_records") != null ? ((Number) s.get("total_records")).longValue() : 0L)
                .sum();

        Map<String, Object> payload = new HashMap<>();
        payload.put("shards", shardData);
        
        Map<String, Object> stats = new HashMap<>();
        stats.put("activeNodes", activeNodes);
        stats.put("totalNodes", shardData.size());
        stats.put("actualLatencyMs", actualLatency);
        stats.put("totalRecords", totalRecords); // New metric
        
        payload.put("stats", stats);

        messagingTemplate.convertAndSend("/topic/telemetry", payload);
    }
}