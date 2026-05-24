package me.renaldohyacinthe.vessel_engine;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;

@SpringBootApplication(exclude = {DataSourceAutoConfiguration.class})
public class VesselEngineApplication {
    public static void main(String[] args) {
        SpringApplication.run(VesselEngineApplication.class, args);
    }
}