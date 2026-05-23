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
        new Thread(() -> {
            try (ServerSocket serverSocket = new ServerSocket(3306)) {
                System.out.println("[Vessel Proxy] Gateway actively listening on port 3306...");
                while (true) {
                    Socket clientSocket = serverSocket.accept();
                    new Thread(() -> handleClient(clientSocket)).start();
                }
            } catch (Exception e) {
                System.err.println("[Vessel Proxy] TCP Server error: " + e.getMessage());
            }
        }).start();
    }

    private void handleClient(Socket clientSocket) {
        String targetShardIp = "10.0.0.2"; 
        
        try (clientSocket; Socket targetSocket = new Socket()) {
            targetSocket.connect(new java.net.InetSocketAddress(targetShardIp, 3306), 3000);
            System.out.println("[Vessel Proxy] Successfully linked to 10.0.0.2. Piping data streams...");

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
            System.err.println("[Vessel Proxy] Backend Shard 1 is completely unresponsive (Timeout).");
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
            // Stream broken, proceed to teardown
        } finally {
            try { s1.close(); } catch (Exception ex) {}
            try { s2.close(); } catch (Exception ex) {}
        }
    }
}