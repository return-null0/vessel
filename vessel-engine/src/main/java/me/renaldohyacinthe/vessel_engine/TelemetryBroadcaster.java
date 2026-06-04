package me.renaldohyacinthe.vessel_engine;

import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
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
        List<Map<String, Object>> currentState = dashboardController.getClusterState();
        
        messagingTemplate.convertAndSend("/topic/telemetry", currentState);
    }
}