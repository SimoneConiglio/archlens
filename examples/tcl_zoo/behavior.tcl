# Behavioral patterns with TclOO: Observer, Strategy, State, Template Method, Command, Chain.
package require TclOO

namespace eval zoo {

    # Subject keeping a list of observers.
    oo::class create EventBus {
        variable observers
        constructor {} { set observers {} }
        method subscribe {observer} { lappend observers $observer }
        method notify {event} {
            foreach o $observers { $o update $event }
        }
    }
    oo::class create AuditLog {
        variable lines
        constructor {} { set lines {} }
        method update {event} { lappend lines $event }
    }

    oo::class create SortStrategy {
        method sort {data} { error "abstract method" }
    }
    oo::class create QuickSort {
        superclass SortStrategy
        method sort {data} { lsort -integer $data }
    }
    oo::class create ReverseSort {
        superclass SortStrategy
        method sort {data} { lsort -integer -decreasing $data }
    }
    oo::class create Sorter {
        variable strategy
        constructor {sortStrategy} { set strategy $sortStrategy }
        method run {data} { $strategy sort $data }
    }

    oo::class create TrafficState {
        method next {light} { error "abstract method" }
    }
    oo::class create Red {
        superclass TrafficState
        method next {light} { $light setState [::zoo::Green new] }
    }
    oo::class create Green {
        superclass TrafficState
        method next {light} { $light setState [::zoo::Red new] }
    }
    oo::class create TrafficLight {
        variable state
        constructor {} { set state [::zoo::Red new] }
        method change {} { $state next [self] }
        method setState {s} { set state $s }
    }

    # Template method: generate defines the skeleton.
    oo::class create Report {
        method generate {} { return "[my header][my body]" }
        method header {} { error "abstract method" }
        method body {} { error "abstract method" }
    }
    oo::class create SalesReport {
        superclass Report
        method header {} { return "Sales\n" }
        method body {} { return "..." }
    }

    oo::class create Command {
        method execute {} { error "abstract method" }
        method undo {} {}
    }
    oo::class create CopyCommand { superclass Command; method execute {} { return copy } }
    oo::class create PasteCommand { superclass Command; method execute {} { return paste } }
    oo::class create CommandHistory {
        variable history
        constructor {} { set history {} }
        method run {cmd} { $cmd execute; lappend history $cmd }
        method undoAll {} { foreach c $history { $c undo } }
    }

    oo::class create Handler {
        variable successor
        constructor {{next ""}} { set successor $next }
        method handle {request} {
            if {$successor ne ""} { return [$successor handle $request] }
            return ""
        }
    }
    oo::class create AuthHandler {
        superclass Handler
        method handle {request} {
            if {$request eq "auth"} { return ok }
            next $request
        }
    }
}
