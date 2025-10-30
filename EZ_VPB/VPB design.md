Date：2025/10/30
By：LdX

摘要：VPB是EZchain最重要的数据结构，它是account可以p2p交易并独立自主验证的根本。故需进行详细的落地设计。

难点与挑战：V（value）、P（Proofs）、B（Block index list）均有各自的数据结构与设计，并且它们的实现逻辑各有不同，将它们在VPB结构中做到一一对应可能在code设计与实现上有困难。

解决方案：VPB结构中将采用三元组设计，V（value）采用AccountValueCollection类；P（Proofs）采用Proofs类；B（Block index list）采用BlockIndexList类。

