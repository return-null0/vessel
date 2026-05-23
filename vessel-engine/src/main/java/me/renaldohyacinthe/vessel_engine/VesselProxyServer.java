package me.renaldohyacinthe.vessel_engine;

import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;

@Component
public class VesselProxyServer implements CommandLineRunner {

    @Override
    public void run(String... args) throws Exception {
        // Run the proxy server in a background thread so it doesn't block Spring's boot cycle
        new Thread(() -> {
            try (ServerSocket serverSocket = new ServerSocket(3306)) {
                System.out.println("[Vessel Proxy] Spring Boot routing engine actively listening on port 3306...");
                
                while (true) {
                    Socket clientSocket = serverSocket.accept();
                    // Basic multi-threaded connection handling for incoming SQL clients
                    new Thread(() -> handleClient(clientSocket)).start();
                }
            } catch (Exception e) {
                System.err.println("[Vessel Proxy] Server crash: " + e.getMessage());
            }
        }).start();
    }

    private void handleClient(Socket clientSocket) {
        // Target Shard 1 by default for the initial protocol handshake handshake
        String targetShardIp = "10.0.0.2"; 
        
        try (Socket targetSocket = new Socket(targetShardIp, 3306);
             InputStream clientIn = clientSocket.getInputStream();
             OutputStream clientOut = clientSocket.getOutputStream();
             InputStream targetIn = targetSocket.getInputStream();
             OutputStream targetOut = targetSocket.getOutputStream()) {

            // Thread to forward SQL Client requests -> Backend MariaDB Shard
            Thread clientToTarget = new Thread(() -> pipeStream(clientIn, targetOut));
            // Thread to forward Backend MariaDB responses -> SQL Client
            Thread targetToClient = new Thread(() -> pipeStream(targetIn, clientOut));

            clientToTarget.start();
            targetToClient.start();

            clientToTarget.join();
            targetToClient.join();

        } catch (Exception e) {
            // Handle silent disconnects cleanly
        }
    }

    private void pipeStream(InputStream in, OutputStream out) {
        byte[] buffer = new byte[4096];
        int bytesRead;
        try {
            while ((bytesRead = in.read(buffer)) != -1) {
                out.write(buffer, 0, bytesRead);
                out.flush();
            }
        } catch (Exception e) {
            // Stream closed
        }
    }
}