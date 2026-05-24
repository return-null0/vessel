package me.renaldohyacinthe.vessel_engine;

import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.web.client.RestTemplate;

import java.sql.DriverManager;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@RestController
public class DashboardController {

    private final List<String> shardIps;
    private final RestTemplate restTemplate;
    private final Map<String, JdbcTemplate> jdbcTemplates = new ConcurrentHashMap<>();

    static {
        try {
            DriverManager.registerDriver(new org.mariadb.jdbc.Driver());
        } catch (Exception e) {
            System.err.println("Fatal: Could not register MariaDB Driver: " + e.getMessage());
        }
    }

    public DashboardController(ClusterConfig clusterConfig, RestTemplateBuilder builder) {
        this.shardIps = clusterConfig.getActiveShardIps();
        this.restTemplate = builder
                .connectTimeout(Duration.ofSeconds(1))
                .readTimeout(Duration.ofSeconds(1))
                .build();
    }

    private JdbcTemplate createTemplate(String ip) {
        DriverManagerDataSource ds = new DriverManagerDataSource();
        ds.setDriverClassName("org.mariadb.jdbc.Driver");
        // Reduced timeout to 1 second to make the dashboard responsive
        ds.setUrl("jdbc:mariadb://" + ip + ":3306/?connectTimeout=1000");
        ds.setUsername("mysql");
        ds.setPassword("vesseladmin");
        return new JdbcTemplate(ds);
    }

    @GetMapping("/api/cluster-state")
    public List<Map<String, Object>> getClusterState() {
        List<Map<String, Object>> results = new ArrayList<>();
        
        for (String targetIp : shardIps) {
            Map<String, Object> shardData = new HashMap<>();
            shardData.put("ip_address", targetIp);
            
            try {
                shardData.put("telemetry", restTemplate.getForObject("http://" + targetIp + ":9090/telemetry", Map.class));
                JdbcTemplate jdbc = jdbcTemplates.computeIfAbsent(targetIp, this::createTemplate);
                jdbc.execute("CREATE DATABASE IF NOT EXISTS appdata");
                shardData.put("records", jdbc.queryForList("SELECT * FROM appdata.cluster_data ORDER BY created_at DESC LIMIT 15"));
                shardData.put("status", "UP");
            } catch (Exception e) {
                jdbcTemplates.remove(targetIp);
                shardData.put("telemetry", Map.of("error", "Offline"));
                shardData.put("records", null);
                shardData.put("status", "DOWN"); 
            }
            results.add(shardData);
        }
        return results;
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
        try { restTemplate.postForObject("http://" + targetIp + ":9090/kill", null, String.class); } catch (Exception ignored) {}
        return Map.of("status", "Killed");
    }

    @PostMapping("/api/restart")
    public Map<String, String> executeRestart(@RequestParam String targetIp) {
        jdbcTemplates.remove(targetIp);
        try { restTemplate.postForObject("http://" + targetIp + ":9090/restart", null, String.class); } catch (Exception ignored) {}
        return Map.of("status", "Restarting");
    }
}