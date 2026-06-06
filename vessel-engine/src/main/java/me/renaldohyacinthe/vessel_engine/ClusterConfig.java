package me.renaldohyacinthe.vessel_engine;

import org.springframework.stereotype.Component;
import java.util.ArrayList;
import java.util.List;

@Component
public class ClusterConfig {

    public List<String> getActiveShardIps() {
        List<String> ips = new ArrayList<>();
        String shardCountStr = System.getenv("VESSEL_SHARD_COUNT");
        int shardCount = (shardCountStr != null) ? Integer.parseInt(shardCountStr) : 10;

        for (int i = 1; i <= shardCount; i++) {
            ips.add("10.0.0." + (i + 1));
        }
        return ips;
    }
}