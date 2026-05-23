package me.renaldohyacinthe.vessel_engine;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import javax.sql.DataSource;
import java.util.HashMap;
import java.util.Map;

@Configuration
public class DataSourceConfig {

    @Bean
    public DataSource dataSource() {
        DataSourceRouter router = new DataSourceRouter();
        Map<Object, Object> targetDataSources = new HashMap<>();

        targetDataSources.put("shard1", createDataSource("10.0.0.2"));
        targetDataSources.put("shard2", createDataSource("10.0.0.3"));
        targetDataSources.put("shard3", createDataSource("10.0.0.4"));

        router.setTargetDataSources(targetDataSources);
        router.setDefaultTargetDataSource(targetDataSources.get("shard1"));
        
        return router;
    }

    private DataSource createDataSource(String ipAddress) {
        DriverManagerDataSource dataSource = new DriverManagerDataSource();
        dataSource.setDriverClassName("org.mariadb.jdbc.Driver");
        dataSource.setUrl("jdbc:mariadb://" + ipAddress + ":3306/mysql");
        dataSource.setUsername("mysql");
        dataSource.setPassword("vesseladmin");
        return dataSource;
    }
}