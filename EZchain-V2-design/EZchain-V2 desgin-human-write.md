
# EZchain-V2设计核心理念文档（非正式版）

## Overview

基于EZchain的设计，对EZchain进行合理优化，主要集中在：主链不再使用Bloom filter，因其所占存储空间大，且存在假阳性问题。本文设计的EZchain-V2的主链区块采用仅单个Merkle tree root设计（也可使用更优的Verkle tree root）。此树聚合全局所有用户节点的最新的交易+状态，其某个叶子节点形为HASH（（用户地址addr，交易bundle，最新高度h1，次新高度h2））。例如：对于用户Alice（假设地址为：0xAlice），Alice最近一次在区块高度h1时提交了交易bundle（即，在#h1号区块，Alice的交易bundle正式被打包上链），Alice次近一次在区块高度h2（h2必然 < h1）时提交了交易bundle'（即，在#h2号区块，Alice的交易bundle'正式被打包上链）。那么目前在最新区块（区块高度 >= h）的Merkle tree中，Alice的状态就是（0xAlice，交易bundle，h1，h2），所以代表Alice的叶子节点的内容也就是HASH（（0xAlice，交易bundle，h1，h2））。这里需要注意的是：所有共识节点必须有义务并且有能力验证：叶子节点HASH（（0xAlice，交易bundle，h1，h2））的信息是正确的，即：1）此叶子节点确实是本区块的Merkle tree root的叶子；2）交易bundle确实是Alice发出的（Alice的签名验证通过）；3）交易bundle确实是h1上链的；4）Alice次近一次交易上链确实发生在h2区块。

在链下用户节点的p2p交易验证环节，原本EZchain的设计是需要交易接收者（Recipient）从主链获取（下载）每个区块的Bloom filter用于验证交易支付者（Sender）有没有隐瞒或欺骗交易区块信息。但采用EZchain-V2的设计，则recipient不再需要从主链下载繁重的Bloom filter，而是仅需存储部分主链的Merkle tree root，例如：Alice的交易bundle在区块高度h1被正式打包上链，此bundle中包含一个交易tx=（Sender：Alice，Recipient：Bob，Value：[0,100]，other info），那么h1区块的Merkle tree必然包含Alice的叶子=HASH（（0xAlice，交易bundle，h1，h2）），其中h2（h2必然 < h1）是Alice上次提交交易bundle的区块。这样，在链下p2p验证tx时，接收者Bob就可以根据Alice提供的叶子信息HASH（（0xAlice，交易bundle，h1，h2））（Alice有义务也有能力提供此叶子信息以及此叶子的树根证明信息），知道上次Alice交易发生在h2，那么Bob就可以继续索取h2的交易信息以验证Alice没有双花欺骗。这个过程类似利用Bloom filter来检测，但是仅需向共识节点索要一个树根信息（很小），且甚至用户节点可以自己存储主链的树根（不用存储整个区块链主链，而是仅存储区块号和merkle tree root就行），不再每次验证向共识节点索取（以存储空间换传输时间）。

不过若采用上述单树根的区块结构，则EZchain原版中的很多细节需要进行相应的修改，例如：交易池结构需要修改，用户节点提交至交易池的内容也需要修改，交易池的验证逻辑也要修改，共识节点间的广播内容及验证算法需要修改（不仅需要广播区块本体，还要广播变更的叶子节点用于辅助验证），链下p2p交易验证的逻辑也需要修改，等等。

## 系统设计模型与网络假设

 1、节点分类：网络中只有两种节点：共识节点和用户节点。
 2、硬件约束：共识节点可以是消费级的个人主机、个人服务器。用户节点则应当是移动端、个人PC等设备。系统设计应当以上述硬件条件（内存、存储、计算能力）作为约束条件。
 3、网络是半同步网络。

## 基础数据结构

 *:部分可详细参考https://github.com/Re20Cboy/EZchain-under-reconstruction- 已完成的代码
 Value：
 Witness：
 Tx：
 ...

## 共识节点数据结构

### 长期存储（数据内容不变）

  区块链区块主体内容：
  1、*交易Merkle tree root*（或者使用优化的Verkle tree）
  2、*other info*: e.g., sig, time, pre hash, nonce, ...

### 长期动态存储（数据内容频繁修改）

  1、*全局用户状态矩阵*：形为n*2的矩阵，用于记录用户最新的交易状态（e.g.,Alice最近一次交易发生在高度为h的区块），n为全局用户数，是动态增加的。

  2、*全局叶子节点集合*：用于生成树，但部分叶子节点会因为每个块打包内容不同，而每轮都变换。

  3、*树中间状态节点集合*：用于加速树生成，避免重复计算（因为全局树会很大）。

  4、*用户未领取的Merkle树证明矩阵*：形为x*2的矩阵（存放最新的用户未领取的“用户Merkle tree proof + 区块高度信息”），x是动态调整的一个参数，用于表示当前还未领取proof的用户节点数量。下面给出一个此矩阵的案例：
  
  | Account addr | proof                                      |
  | ------------ | ------------------------------------------ |
  | 0X_Alice     | Alice_Merkle_tree_proof +  此状态对应块高度|
  | 0X_Bob       | Bob_Merkle_tree_proof +    此状态对应块高度|
  
  其中:
  Alice_state_Merkle_tree_proof ：账户Alice的Merkle树证明

### 交易池（mempool）数据结构（各自的交易池由各自的共识节点维护）

#### 用户提交至交易池的Bundle结构应当初步设计（可以根据实际情况进行修改）

  Bundle {
   version
   chain_id
   seq
   expiry_height
   fee
   bundle_hash
   anti_spam_nonce
   sig
   }
   说明：
   seq
    sender 本地递增序号，用来防 replay、去重、替换
   expiry_height
    防止旧包永久滞留和重放
   bundle_hash
    完整 sidecar/bundle 的 hash
   anti_spam_nonce
    反垃圾、PoW、rate-limit 插件可挂这里
   sig
    65 bytes recoverable signature
  *：这里的Bundle采用“Ethereum 式地址恢复”

#### 用户如何给Bundle签名？

  不建议给每一笔子交易都单独签名，对EZchain来说，最合理的是：只签 Bundle，不签内部每个tx。不要签 JSON。一定要签规范化二进制编码：
  SigHash = Keccak256(
  domain_separator ||
  canonical_encode(
    version,
    chain_id,
    seq,
    expiry_height,
    fee,
    bundle_hash,
    claim_set_hash,
    anti_spam_nonce
   )
  )
  再用 secp256k1 recoverable ECDSA 签。
  这里有 3 个必须做的点：
  加 domain_separator
   例如："EZCHAIN_ENVELOPE_V1"
   防止别的消息类型复用签名
  加 chain_id
   防跨链重放
   类似 Ethereum 的 EIP-155 思路
  强制 low-s
   防签名可塑性

#### 共识节点收到Bundle后的mempool前置验证流程
  
  计算 SigHash；
  用 sig 恢复 pubkey；
  从 pubkey 导出 sender_addr；
  检测此sender_addr是否在*用户未领取的Merkle树证明矩阵*有未领取的证明，若有则拒绝此提交，并与此用户通讯：向其发送“Merkle树证明”，其确认收到后，才有资格提交新的bundle；
  检查签名是否合法、low-s 是否满足；
  检查 chain_id / expiry / size / anti-spam；
  拉取或检查对应 sidecar；
  验证 hash(sidecar) == bundle_hash；
  把这条记录放进mempool，并按 sender_addr 建索引，注意这里需保证与EZchain原版相同的规则，即，每个mempool中，一个sender_addr仅能有至多1个bundle（多于一个bundle则认为后来的那个为非法，直接丢弃）。

#### 交易池更新策略

在新区块被确认上链后执行：
本轮出块的winner共识节点很简单，就是把已打包进块的Bundle从交易池中剔除即可。
非winner的共识节点则需要根据收到的*辅助验证数据*（详见下文）来进行mempool更新。具体地，根据*辅助验证数据*中的bundle来查找并删除本地的相同bundle。

### 共识节点如何打包mempool中的Bundle以形成new block？

 按照一定的排序规则（例如：fifo或fee排序）打包所有的合法bundle，并用每个bundle形成一个leaf：
 leaf=HASH（（0x_sender_addr，Bundle，h1，h2）），其中h1就是本次打包的区块的高度，h2则由共识节点查询本地的“全局用户状态矩阵”获得（若本区块上链，则“全局用户状态矩阵”中记录的最新高度就正好是h2了）；0x_sender_addr来自于从Bundle中恢复出来的sender的地址。
 然后从此轮mempool生成的*新叶子节点集合*去更新全局叶子节点集合（部分更新替换），保持全局所有叶子节点都是最新的。
 然后用最新的叶子节点再去更新“树中间状态节点集合”，不是全量更新，而是部分更新（树中节点有变化的则更新）。
 最后再生成最新的Merkle tree root，并结合其他信息生成最新的区块。

### 共识节点如何与其他共识节点通讯，广播什么信息？

 除了传统的共识节点间的区块广播外，还需要广播*辅助验证数据*。
 *辅助验证数据*这里主要是指*新叶子节点集合*，因为原理上，如果*新叶子节点集合*被所有共识节点获得，那么所有共识节点都可本地更新自己的全局叶子节点集合以及树中间状态节点集合，从而验证区块内容中的merkle tree root是否正确。

### 共识节点如何与本此打包Bundle中相关联的sender用户通讯？

在原始的EZchain中，共识节点（本轮mine的winner）需要给本轮打包的所有sender分发证明数据。在EZchain-V2中，同样需要此步骤，但分发的数据有些许差异。具体地，在EZchain-V2中，分发给用户的证明数据应该是“用户Merkle tree proof + 区块高度信息”，不过考虑到用户是移动端或端侧设备的假设，用户可能随意地离线，因此，此分发过程可能无法完成，对于分发失败的情况，则参考*用户未领取的Merkle树证明矩阵*中的描述，将分发失败的证明数据添加到此矩阵中。

## 用户节点数据结构

### 长期存储

用户节点需要长期存储的主要数据结构就是Value-Witness对，不过相较于原始的EZchain，EZchain-V2的Witness有些改变。EZchain-V2的witness数据结构不再需要针对bloom filter的证明，而只需要存储单merkle tree的路径证明。
v-w对的真实存储逻辑还是采用目前github.com/Re20Cboy/EZchain-under-reconstruction- 仓库中已完成的链式存储逻辑，因为这样的存储最节省空间。

### 短期存储

...

### 链下p2p交易验证

此部分也是与EZchain最大的不同，由于主链数据结构的改变，链下的验证算法流程也发生了较大的变化。这里我们沿用前文所述的案例进行更加详细的拆解分析：
Alice的交易bundle在区块高度h1被正式打包上链，此bundle中包含一个交易tx=（Sender：Alice，Recipient：Bob，Value：[0,100]，other info）。
那么h1区块的Merkle tree必然包含Alice的叶子=HASH（（0xAlice，bundle，h1，h2）），其中h2（h2必然 < h1）是Alice上次提交交易bundle的区块。
这样，在链下p2p验证tx时：
step1: 接收者Bob就可以根据Alice提供的叶子信息HASH（（0xAlice，bundle，h1，h2））（Alice有义务也有能力提供此叶子的树根证明以及（0xAlice，交易bundle，h1，h2）的数据主体），Bob就知道上次Alice交易发生在h2，那么Bob就可以继续索取h2的交易信息以验证Alice没有双花欺骗。
step2: Alice则必须提供h2区块中的对应的叶子信息HASH（（0xAlice，bundle'，h2，h3）），Bob就可以检查Bundle'中，Value：[0,100]有没有被Alice提前花销，若有，则拒绝交易；若没有，则继续溯源h3区块对应的Alice的信息。
step3: ...
以此循环，直到溯源到创始块，或遇到Bob的检查点（checkpoint）。
上述整个过程中Bob所需要的外部验证信息（即，除Alice提供的数据外），仅需要h1、h2、h3、...高度的区块中的merkle tree root即可（这相较于原始EZchain的bloom filter而言，传输、存储的成本都非常小）。

### 检查点（checkpoint）机制

此机制和原理与原版的EZchain中没有太多区别，只要能契合最新EZchain-V2的数据结构即可。