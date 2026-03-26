package com.srm.web;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.domain.EntityScan;
import org.springframework.context.annotation.ComponentScan;
import org.springframework.data.jpa.repository.config.EnableJpaAuditing;
import org.springframework.data.jpa.repository.config.EnableJpaRepositories;
import org.springframework.scheduling.annotation.EnableAsync;

@SpringBootApplication
@EnableAsync
@EnableJpaAuditing
@ComponentScan(basePackages = "com.srm")
@EntityScan(basePackages = "com.srm")
@EnableJpaRepositories(basePackages = "com.srm")
public class SrmApplication {

    public static void main(String[] args) {
        SpringApplication.run(SrmApplication.class, args);
    }
}
