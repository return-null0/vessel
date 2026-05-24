package me.renaldohyacinthe.vessel_engine;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import javax.sql.DataSource;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Configuration
public class DataSourceConfig {

    private final ClusterConfig clusterConfig;

    public DataSourceConfig(ClusterConfig clusterConfig) {
        this.clusterConfig = clusterConfig;
    }

    @Bean
    public DataSource dataSource() {
        DataSourceRouter router = new DataSourceRouter();
        Map<Object, Object> targetDataSources = new HashMap<>();
        List<String> activeIps = clusterConfig.getActiveShardIps();

        for (int i = 0; i < activeIps.size(); i++) {
            targetDataSources.put("shard" + (i + 1), createDataSource(activeIps.get(i)));
        }

        router.setTargetDataSources(targetDataSources);
        router.setDefaultTargetDataSource(targetDataSources.get("shard1"));
        
        return router;
    }

    private DataSource createDataSource(String ipAddress) {
        DriverManagerDataSource dataSource = new DriverManagerDataSource();
        dataSource.setDriverClassName("org.mariadb.jdbc.Driver");
        dataSource.setUrl("jdbc:mariadb://" + ipAddress + ":3306/appdata");
        dataSource.setUsername("mysql");
        dataSource.setPassword("vesseladmin");
        return dataSource;
    }
}