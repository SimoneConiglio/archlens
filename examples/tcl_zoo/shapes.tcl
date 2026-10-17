# Shape hierarchy: Composite, Visitor, Prototype.
package require TclOO

namespace eval zoo {

    # Abstract component of the shape tree.
    oo::class create Shape {
        variable origin
        constructor {} { set origin {0 0} }
        method area {} { error "abstract method: subclass must implement area" }
        method accept {visitor} { error "abstract method" }
        method clone {} { return [oo::copy [self]] }
    }

    oo::class create Circle {
        superclass Shape
        variable radius
        constructor {r} { next; set radius $r }
        method area {} { expr {3.14159 * $radius * $radius} }
        method accept {visitor} { $visitor visitCircle [self] }
    }

    oo::class create Square {
        superclass Shape
        variable side
        constructor {s} { next; set side $s }
        method area {} { expr {$side * $side} }
        method accept {visitor} { $visitor visitSquare [self] }
    }

    # Composite: a shape made of shapes.
    oo::class create Group {
        superclass Shape
        variable children
        constructor {} { next; set children {} }
        method add {shape} { lappend children $shape; return [self] }
        method area {} {
            set total 0
            foreach child $children { set total [expr {$total + [$child area]}] }
            return $total
        }
        method accept {visitor} { $visitor visitGroup [self] }
    }

    oo::class create AreaVisitor {
        variable total
        constructor {} { set total 0 }
        method visitCircle {c} { set total [expr {$total + [$c area]}] }
        method visitSquare {s} { set total [expr {$total + [$s area]}] }
        method visitGroup {g} { set total [expr {$total + [$g area]}] }
        method total {} { return $total }
    }
}
