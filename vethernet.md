# To enable full internet access in Shell mode

## On the host

1. Creating the Virtual Cable

```sh
# Create the veth pair
sudo ip link add v-host type veth peer name v-guest
```

In Linux, a veth (virtual ethernet) device always comes in a pair. You can think of this as a virtual Ethernet cable. Whatever packets you push into v-host will instantly pop out of v-guest, and vice versa. At this exact moment, both ends of the cable are sitting in your Ubuntu host's default network namespace.

2. Crossing the Namespace Boundary

```sh
# Move the guest end into the container (using your PID )
sudo ip link set v-guest netns PID
```
taking the v-guest end of the virtual cable and pushing it through into the container's isolated network namespace. The moment you press enter, v-guest vanishes from your Ubuntu host's ip link output. It now exists exclusively inside the container.

3. Establishing the Gateway

```sh
# Assign the gateway IP to the host end
sudo ip addr add 10.0.0.1/24 dev v-host
sudo ip link set v-host up
```

Now that the cable spans across the namespaces, you need to turn the Ubuntu side into a router. By assigning 10.0.0.1 to v-host, you are establishing the "Default Gateway" IP address that the container will eventually look for when it tries to reach the outside world.

4. Enable IP forwarding in the Linux kernel
```sh
sudo sysctl -w net.ipv4.ip_forward=1
```
By default, the Linux kernel drops any packets it receives that are not explicitly destined for itself. Since the container will be sending packets destined for google.com to the v-host interface, the Ubuntu kernel needs permission to act as a middleman and forward those packets along.

5. Setup NAT/Masquerade (Replace 'eth0' with your actual host interface if different)


```sh
sudo iptables -t nat -A POSTROUTING -s 10.0.0.0/24 -o eth0 -j MASQUERADE
```

Your container's IP (10.0.0.2) is a private address. If it tries to talk to a public server, that server will have no idea how to route the reply back to a private subnet. The iptables MASQUERADE rule tells your Ubuntu host to rewrite the outbound packets so they look like they came from the host's primary interface (eth0). When the reply comes back, the host automatically untangles the translation and passes the packet down the virtual cable to the container.

### In the container
6. Container Configuration


```sh
# Bring the new interface up
ip link set v-guest up

# Assign the container's IP
ip addr add 10.0.0.2/24 dev v-guest

# Set the default route to point to the Ubuntu Host
ip route add default via 10.0.0.1

```