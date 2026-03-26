# Aliyun ECS Troubleshooting

This note captures the specific ECS issues we hit during EZchain V2 multi-host testing.

## Login Pitfall: Private vs Public Login

When using the Aliyun ECS login panel, the login target may default to a private IP.

Example of the wrong target:

- `root@172.19.x.x:22`

This is usually an internal VPC address. It is not the address to use from a local laptop on the public internet.

### Correct rule

- If logging in from a local Mac/PC, use the ECS public IP or EIP.
- If the login dialog is showing `172.19.x.x`, switch the login target from private network to public network first.
- If the public option works, the instance itself may be healthy and the original failure was just caused by choosing the wrong login path.

## Tailscale Reminder

For the current EZchain setup:

- Mac and ECS communicate over Tailscale `100.x.x.x` addresses.
- Tailscale must remain online during testing.
- If cross-host EZchain transactions time out, verify Tailscale reachability before changing protocol code again.

## Quick Checks

After logging in, run:

```bash
tailscale status
ss -ltnp | grep 22
ss -ltnp | grep 19500
ss -ltnp | grep 19501
ss -ltnp | grep 19600
```

What these tell us:

- `tailscale status`: whether the node is still online in the tailnet
- `22`: whether SSH is listening
- `19500/19501`: consensus nodes
- `19600`: account node

## SSH Notes

- Password login does not need a private key.
- Key-pair login requires the private key saved when the key was created.
- If the key is unavailable, use ECS VNC, then either:
  - set a root password with `passwd root`, or
  - add a new SSH public key to `/root/.ssh/authorized_keys`

## Practical Rule For Future Debugging

Before assuming a V2 protocol bug, confirm these three things first:

1. Are we logging in through the public IP rather than the ECS private IP?
2. Is Tailscale online on both machines?
3. Are the remote ports actually listening and reachable?
