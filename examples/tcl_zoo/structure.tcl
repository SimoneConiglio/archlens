# Creational and structural patterns: Singleton, Factory, Builder, Decorator, Proxy, Adapter, Facade.
package require TclOO

namespace eval zoo {

    # Process-wide configuration: classic TclOO singleton through a class method.
    oo::class create Config {
        self method instance {} {
            my variable instance
            if {![info exists instance]} { set instance [my new] }
            return $instance
        }
        variable values
        constructor {} { set values [dict create] }
        method get {key} { dict get $values $key }
        method set {key value} { dict set values $key $value }
    }

    # Registry-based factory: classes are registered by name and created on demand.
    oo::class create ShapeFactory {
        variable registry
        constructor {} {
            set registry [dict create]
            my register circle ::zoo::Circle
            my register square ::zoo::Square
        }
        method register {name cls} { dict set registry $name $cls }
        method create {name args} {
            set cls [dict get $registry $name]
            return [$cls new {*}$args]
        }
    }

    oo::class create QueryBuilder {
        variable table fields limit
        constructor {t} { set table $t; set fields {}; set limit -1 }
        method select {f} { lappend fields $f; return [self] }
        method limit {n} { set limit $n; return [self] }
        method build {} { return [list $table $fields $limit] }
    }

    oo::class create DataSource {
        method read {} { error "abstract method" }
        method write {data} { error "abstract method" }
    }
    oo::class create FileDataSource {
        superclass DataSource
        variable path
        constructor {p} { set path $p }
        method read {} { return "" }
        method write {data} { return }
    }
    oo::class create CompressionDecorator {
        superclass DataSource
        variable wrapped
        constructor {dataSource} { set wrapped $dataSource }
        method read {} { return [$wrapped read] }
        method write {data} { $wrapped write $data }
    }
    oo::class create LazyDataSource {
        superclass DataSource
        variable path real
        constructor {p} { set path $p; set real "" }
        method Load {} {
            if {$real eq ""} { set real [::zoo::FileDataSource new $path] }
            return $real
        }
        method read {} { [my Load] read }
        method write {data} { [my Load] write $data }
    }
    oo::class create LegacyStorage {
        method fetchBlob {key} { return $key }
        method putBlob {key blob} { return }
    }
    oo::class create LegacyStorageAdapter {
        superclass DataSource
        variable storage key
        constructor {legacyStorage k} { set storage $legacyStorage; set key $k }
        method read {} { $storage fetchBlob $key }
        method write {data} { $storage putBlob $key $data }
    }

    oo::class create Inventory { method reserve {sku} { return 1 } }
    oo::class create Payments { method charge {amount} { return 1 } }
    oo::class create Shipping { method ship {sku} { return tracking } }
    oo::class create OrderFacade {
        variable inventory payments shipping
        constructor {} {
            set inventory [::zoo::Inventory new]
            set payments [::zoo::Payments new]
            set shipping [::zoo::Shipping new]
        }
        method placeOrder {sku amount} {
            $inventory reserve $sku
            $payments charge $amount
            $shipping ship $sku
        }
    }

    # A class extended later with oo::define, and a mixin.
    oo::class create Logging {
        method log {msg} { puts stderr $msg }
    }
    oo::define OrderFacade mixin Logging
}
