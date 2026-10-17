# Exercises the zoo so `tclsh demo.tcl` proves the example runs.
set dir [file dirname [info script]]
foreach f {shapes.tcl behavior.tcl structure.tcl} { source [file join $dir $f] }
namespace eval zoo {
    set g [Group new]
    $g add [Circle new 1]
    $g add [Square new 2]
    set v [AreaVisitor new]
    $g accept $v
    puts "area via visitor: [format %.2f [$v total]]"
    puts "sorted: [[Sorter new [ReverseSort new]] run {3 1 2}]"
    set bus [EventBus new]; set log [AuditLog new]; $bus subscribe $log; $bus notify hello
    puts "same config: [expr {[Config instance] eq [Config instance]}]"
    puts "factory: [info object class [[ShapeFactory new] create circle 2]]"
    puts "query: [[[[QueryBuilder new users] select name] limit 5] build]"
    set h [AuthHandler new [Handler new]]; puts "chain: [$h handle auth]"
    puts "report: [string trim [[SalesReport new] generate]]"
    puts "adapter: [[LegacyStorageAdapter new [LegacyStorage new] k1] read]"
    puts "order: [[OrderFacade new] placeOrder sku1 9.5]"
    set light [TrafficLight new]; $light change; puts "traffic light switched"
    puts "clone: [info object class [[Circle new 3] clone]]"
}
