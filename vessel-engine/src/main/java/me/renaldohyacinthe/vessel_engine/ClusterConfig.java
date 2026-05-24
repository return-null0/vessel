package me.renaldohyacinthe.vessel_engine;

import org.springframework.context.annotation.Configuration;
import java.util.ArrayList;
import java.util.List;

@Configuration
public class ClusterConfig {

    public List<String> getActiveShardIps() {
        String countStr = System.getenv("VESSEL_SHARD_COUNT");
        int count = (countStr != null && !countStr.isEmpty()) ? Integer.parseInt(countStr) : 3;
        
        List<String> ips = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            ips.add("10.0.0." + (i + 2));
        }
        return ips;
    }
}