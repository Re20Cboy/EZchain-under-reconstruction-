Date：2025/10/31
By：LdX

摘要：VPB是EZchain最重要的数据结构，它是account可以p2p交易并独立自主验证的根本。故需进行详细的落地设计。

难点与挑战：V（value）、P（Proofs）、B（Block index list）均有各自的数据结构与设计，并且它们的实现逻辑各有不同，将它们在VPB结构中做到一一对应可能在code设计与实现上有困难。

现状：V（value）采用AccountValueCollection类（注意，这里的AccountValueCollection已经完成了对一个account的所有复数个value的集中化管理接口）；P（Proofs）采用Proofs类；B（Block index list）采用BlockIndexList类。
V（value）、P（Proofs）、B（Block index list）在逻辑上是一一对应的关系，具体地，一个Value，对应一个Proofs，对应一个Block index list。目前的AccountValueCollection是利用链式结构管理Value；Proofs使用映射表来记录Proof unit的关系；BlockIndexList采用双表单结构来记录相应区块号和对应owner关系。

解决方案（拟）：据上所述，若想建立起V-P-B的一一对应关系，需要在它们之间再建立起新的映射关系，具体地：AccountValueCollection中的一个ValueNode（主要是其中的Value）和唯一的Proofs对应起来，并和唯一的BlockIndexList对应起来。VPBPairs中应包含一个AccountValueCollection的对象，及其所有Value node对应的P（Proofs）、B（Block index list）的映射关系。
VPBPairs还需提供一些必要的功能接口（因其是Account管理VPB的唯一渠道），包括但不限于：添加新的VPB对，这需要提供一个接口，并调用AccountValueCollection、Proofs及BlockIndexList相关的接口，并建立一一映射；删除VPB对；查询VPB对（尤其是对AccountPickValues的支持）；编辑VPB对（在系统运行，交易不断累加的过程中，某个value对应的P和B都是在不断变化的）等。
VPBPairs还需相关必要数据的永久存储，因为用户需要随时在离线，这样会需要永久存储或随时读取硬盘中的VPBPairs，当然存储的数据主要是V、P、B的核心数据，然后重构出VPBPairs对象。

另外，VPBPairs还需要集成AccountPickValues.py的值选择功能，也需要调用AccountPickValues.py中的算法（VPBPairs中的AccountValueCollection就是需要传给AccountPickValues的）。