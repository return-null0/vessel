package me.renaldohyacinthe.vessel_engine;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.stereotype.Service;
import java.util.*;
import java.util.concurrent.*;

@Service
public class ScatterGatherService {

    private final List<String> shards;
    private final Map<String, JdbcTemplate> jdbcTemplates = new ConcurrentHashMap<>();

    public ScatterGatherService(ClusterConfig clusterConfig) {
        this.shards = clusterConfig.getActiveShardIps();
    }

    private JdbcTemplate createTemplate(String ip) {
        DriverManagerDataSource ds = new DriverManagerDataSource();
        ds.setDriverClassName("org.mariadb.jdbc.Driver");
        ds.setUrl("jdbc:mariadb://" + ip + ":3306/appdata?connectTimeout=300&socketTimeout=300&maxRetries=0");
        ds.setUsername("mysql");
        ds.setPassword("vesseladmin");
        return new JdbcTemplate(ds);
    }

    public Map<String, Object> generateGlobalReport() {
        Map<String, Object> aggregatedResults = new ConcurrentHashMap<>();
        long startTime = System.currentTimeMillis();

        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            List<CompletableFuture<Void>> futures = shards.stream()
                .map(ip -> CompletableFuture.runAsync(() -> {
                    aggregatedResults.put("Shard_" + ip, queryShard(ip));
                }, executor))
                .toList();

            CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).join();
        }

        aggregatedResults.put("execution_time_ms", System.currentTimeMillis() - startTime);
        return aggregatedResults;
    }

    private Map<String, Object> queryShard(String ip) {
        Map<String, Object> data = new HashMap<>();
        try {
            JdbcTemplate jdbc = jdbcTemplates.computeIfAbsent(ip, this::createTemplate);
            jdbc.execute("SELECT 1"); 
            
            List<Map<String, Object>> records = jdbc.queryForList("SELECT shard_key, payload FROM cluster_data LIMIT 50");
            Long count = jdbc.queryForObject("SELECT COUNT(*) FROM cluster_data", Long.class);
            data.put("records", records);
            data.put("total_records", count != null ? count : 0);
            data.put("status", "ONLINE");
        } catch (Exception e) {
            jdbcTemplates.remove(ip);
            data.put("status", "OFFLINE");
            data.put("total_records", 0); 
            data.put("error", e.getMessage());
        }
        return data;
    }
}