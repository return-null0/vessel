package me.renaldohyacinthe.vessel_engine;

import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.web.client.RestTemplate;

import java.sql.DriverManager;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.stream.Collectors;

@RestController
public class DashboardController {

    private final List<String> shardIps;
    private final RestTemplate restTemplate;
    private final ScatterGatherService scatterGatherService;
    private final Map<String, JdbcTemplate> jdbcTemplates = new ConcurrentHashMap<>();

    static {
        try {
            DriverManager.registerDriver(new org.mariadb.jdbc.Driver());
        } catch (Exception e) {
            System.err.println("Fatal: Could not register MariaDB Driver: " + e.getMessage());
        }
    }

    public DashboardController(ClusterConfig clusterConfig, RestTemplateBuilder builder, ScatterGatherService scatterGatherService) {
        this.shardIps = clusterConfig.getActiveShardIps();
        this.scatterGatherService = scatterGatherService;
        this.restTemplate = builder
                .connectTimeout(Duration.ofMillis(300))
                .readTimeout(Duration.ofMillis(300))
                .build();
    }

    private JdbcTemplate createTemplate(String ip) {
        DriverManagerDataSource ds = new DriverManagerDataSource();
        ds.setDriverClassName("org.mariadb.jdbc.Driver");
        ds.setUrl("jdbc:mariadb://" + ip + ":3306/appdata?connectTimeout=300&socketTimeout=300");
        ds.setUsername("mysql");
        ds.setPassword("vesseladmin");
        return new JdbcTemplate(ds);
    }

@GetMapping("/api/cluster-state")
    public List<Map<String, Object>> getClusterState() {
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            
            CompletableFuture<Map<String, Object>> dbReportFuture = CompletableFuture.supplyAsync(
                scatterGatherService::generateGlobalReport, executor
            );

            List<CompletableFuture<Map<String, Object>>> telemetryFutures = shardIps.stream()
                .map(targetIp -> CompletableFuture.supplyAsync(() -> {
                    Map<String, Object> partialData = new HashMap<>();
                    partialData.put("ip_address", targetIp);
                    try {
                        partialData.put("telemetry", restTemplate.getForObject("http://" + targetIp + ":9090/telemetry", Map.class));
                    } catch (Exception e) {
                        partialData.put("telemetry", Map.of("error", "Watcher Offline"));
                    }
                    return partialData;
                }, executor))
                .toList();

            Map<String, Object> globalReport = dbReportFuture.join();

            return telemetryFutures.stream().map(future -> {
                Map<String, Object> shardData = future.join();
                String targetIp = (String) shardData.get("ip_address");
                
                @SuppressWarnings("unchecked")
                Map<String, Object> dbData = (Map<String, Object>) globalReport.get("Shard_" + targetIp);
                
                if (dbData != null) {
                    shardData.putAll(dbData);
                    if ("OFFLINE".equals(dbData.get("status")) && !shardData.get("telemetry").toString().contains("error")) {
                        shardData.put("status", "BOOTING");
                        shardData.put("records", null);
                    } else if ("ONLINE".equals(dbData.get("status"))) {
                        shardData.put("status", "UP");
                    } else {
                        shardData.put("status", "DOWN");
                    }
                } else {
                    shardData.put("status", "DOWN");
                }
                
                return shardData;
            }).collect(Collectors.toList());
        }
    }

    @GetMapping("/api/shard-records")
    public List<Map<String, Object>> getShardRecords(@RequestParam String targetIp) {
        try {
            JdbcTemplate jdbc = jdbcTemplates.computeIfAbsent(targetIp, this::createTemplate);
            return jdbc.queryForList("SELECT * FROM appdata.cluster_data ORDER BY created_at DESC");
        } catch (Exception e) {
            return Collections.emptyList();
        }
    }

    @GetMapping("/api/unshard")
    public List<Map<String, Object>> performUnsharding() {
        List<Map<String, Object>> masterDatabase = new ArrayList<>();
        for (String targetIp : shardIps) {
            try {
                JdbcTemplate jdbc = jdbcTemplates.computeIfAbsent(targetIp, this::createTemplate);
                masterDatabase.addAll(jdbc.queryForList("SELECT *, '" + targetIp + "' as source_node FROM appdata.cluster_data ORDER BY created_at DESC"));
            } catch (Exception ignored) {}
        }
        return masterDatabase;
    }

    @PostMapping("/api/kill")
    public Map<String, String> executeHardwareKill(@RequestParam String targetIp) {
        jdbcTemplates.remove(targetIp);
        try {
            restTemplate.postForObject("http://" + targetIp + ":9090/kill", null, String.class);
        } catch (Exception ignored) {}
        return Map.of("status", "Killed");
    }

    @PostMapping("/api/restart")
    public Map<String, String> executeRestart(@RequestParam String targetIp) {
        jdbcTemplates.remove(targetIp);
        try {
            restTemplate.postForObject("http://" + targetIp + ":9090/restart", null, String.class);
        } catch (Exception ignored) {}
        return Map.of("status", "Restarting");
    }

    @PostMapping("/api/global-kill")
    public ResponseEntity<String> globalKill() {
        System.out.println("[CRITICAL] Global cluster shutdown sequence initiated via Web UI.");
        for (String ip : shardIps) {
            try {
                System.out.println("Sending SIGTERM to Shard: " + ip);
                restTemplate.postForEntity("http://" + ip + ":9090/kill", null, String.class);
            } catch (Exception e) {
                System.err.println("Shard " + ip + " is already offline or unreachable.");
            }
        }
        new Thread(() -> {
            try {
                Thread.sleep(1000); 
                System.out.println("[CRITICAL] Router supervisor shutting down container.");
                restTemplate.postForEntity("http://127.0.0.1:9090/kill", null, String.class);
            } catch (Exception e) {
                System.exit(0);
            }
        }).start();
        return ResponseEntity.ok("{\"status\": \"Cluster shutdown initiated\"}");
    }
}