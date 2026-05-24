package me.renaldohyacinthe.vessel_engine;

import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

@Component
public class VesselProxyServer implements CommandLineRunner {

    private final List<String> shards;
    private final AtomicInteger requestCounter = new AtomicInteger(0);

    public VesselProxyServer(ClusterConfig clusterConfig) {
        this.shards = clusterConfig.getActiveShardIps();
    }

    @Override
    public void run(String... args) throws Exception {
        new Thread(() -> {
            try (ServerSocket serverSocket = new ServerSocket(3306)) {
                System.out.println("[Vessel Proxy] Gateway balancing across " + shards.size() + " shards on port 3306...");
                while (true) {
                    Socket clientSocket = serverSocket.accept();
                    int targetIndex = requestCounter.getAndIncrement() % shards.size();
                    String selectedShard = shards.get(targetIndex);
                    new Thread(() -> handleClient(clientSocket, selectedShard)).start();
                }
            } catch (Exception e) {
                System.err.println("[Vessel Proxy] TCP Server error: " + e.getMessage());
            }
        }).start();
    }

    private void handleClient(Socket clientSocket, String targetShardIp) {
        try (clientSocket; Socket targetSocket = new Socket()) {
            targetSocket.connect(new java.net.InetSocketAddress(targetShardIp, 3306), 3000);
            System.out.println("[Vessel Proxy] Routing connection to Shard " + targetShardIp);

            InputStream clientIn = clientSocket.getInputStream();
            OutputStream clientOut = clientSocket.getOutputStream();
            InputStream targetIn = targetSocket.getInputStream();
            OutputStream targetOut = targetSocket.getOutputStream();

            Thread clientToTarget = new Thread(() -> pipeStream(clientIn, targetOut, clientSocket, targetSocket));
            Thread targetToClient = new Thread(() -> pipeStream(targetIn, clientOut, clientSocket, targetSocket));

            clientToTarget.start();
            targetToClient.start();

            clientToTarget.join();
            targetToClient.join();

        } catch (java.net.SocketTimeoutException e) {
            System.err.println("[Vessel Proxy] Backend Shard " + targetShardIp + " is unresponsive.");
        } catch (Exception e) {
            System.err.println("[Vessel Proxy] Routing failed: " + e.getMessage());
        }
    }

    private void pipeStream(InputStream in, OutputStream out, Socket s1, Socket s2) {
        byte[] buffer = new byte[4096];
        int bytesRead;
        try {
            while ((bytesRead = in.read(buffer)) != -1) {
                out.write(buffer, 0, bytesRead);
                out.flush();
            }
        } catch (Exception e) {
        } finally {
            try { s1.close(); } catch (Exception ex) {}
            try { s2.close(); } catch (Exception ex) {}
        }
    }
}