#pragma once
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace zoo::app {

// ---- Strategy ---------------------------------------------------------------
class SortStrategy {
 public:
  virtual ~SortStrategy() = default;
  virtual void sort(std::vector<int>& data) = 0;
};
class QuickSort : public SortStrategy {
 public:
  void sort(std::vector<int>& data) override;
};
class MergeSort : public SortStrategy {
 public:
  void sort(std::vector<int>& data) override;
};
class Sorter {
 public:
  explicit Sorter(std::unique_ptr<SortStrategy> strategy) : strategy_(std::move(strategy)) {}
  void run(std::vector<int>& data) { strategy_->sort(data); }

 private:
  std::unique_ptr<SortStrategy> strategy_;
};

// ---- State ------------------------------------------------------------------
class TrafficLight;
class TrafficState {
 public:
  virtual ~TrafficState() = default;
  virtual void next(TrafficLight& light) = 0;
};
class Red : public TrafficState {
 public:
  void next(TrafficLight& light) override;
};
class Green : public TrafficState {
 public:
  void next(TrafficLight& light) override;
};
class TrafficLight {
 public:
  TrafficLight() : state_(std::make_unique<Red>()) {}
  void change() { state_->next(*this); }
  void setState(std::unique_ptr<TrafficState> s) { state_ = std::move(s); }

 private:
  std::unique_ptr<TrafficState> state_;
};

// ---- Template Method ----------------------------------------------------------
class Report {
 public:
  virtual ~Report() = default;
  std::string generate() { return header() + body() + footer(); }

 protected:
  virtual std::string header() = 0;
  virtual std::string body() = 0;
  virtual std::string footer() { return ""; }
};
class SalesReport : public Report {
 protected:
  std::string header() override { return "Sales\n"; }
  std::string body() override { return "..."; }
};

// ---- Command ----------------------------------------------------------------
class Command {
 public:
  virtual ~Command() = default;
  virtual void execute() = 0;
  virtual void undo() {}
};
class CopyCommand : public Command {
 public:
  void execute() override {}
};
class PasteCommand : public Command {
 public:
  void execute() override {}
};
class CommandHistory {
 public:
  void run(std::unique_ptr<Command> cmd) {
    cmd->execute();
    history_.push_back(std::move(cmd));
  }
  void undoAll() {
    for (auto& cmd : history_) cmd->undo();
  }

 private:
  std::vector<std::unique_ptr<Command>> history_;
};

// ---- Builder ----------------------------------------------------------------
struct Query {
  std::string table;
  std::vector<std::string> fields;
  int limit = -1;
};
class QueryBuilder {
 public:
  explicit QueryBuilder(std::string table) { query_.table = std::move(table); }
  QueryBuilder& select(const std::string& field) {
    query_.fields.push_back(field);
    return *this;
  }
  QueryBuilder& limit(int n) {
    query_.limit = n;
    return *this;
  }
  Query build() const { return query_; }

 private:
  Query query_;
};

// ---- Abstract Factory -------------------------------------------------------
class Button {
 public:
  virtual ~Button() = default;
  virtual std::string render() const = 0;
};
class Checkbox {
 public:
  virtual ~Checkbox() = default;
  virtual void toggle() = 0;
};
class DarkButton : public Button {
 public:
  std::string render() const override { return "<dark>"; }
};
class DarkCheckbox : public Checkbox {
 public:
  void toggle() override {}
};
class WidgetFactory {
 public:
  virtual ~WidgetFactory() = default;
  virtual std::unique_ptr<Button> createButton() const = 0;
  virtual std::unique_ptr<Checkbox> createCheckbox() const = 0;
};
class DarkWidgetFactory : public WidgetFactory {
 public:
  std::unique_ptr<Button> createButton() const override { return std::make_unique<DarkButton>(); }
  std::unique_ptr<Checkbox> createCheckbox() const override { return std::make_unique<DarkCheckbox>(); }
};

// ---- Decorator / Proxy / Adapter / Facade ------------------------------------
class DataSource {
 public:
  virtual ~DataSource() = default;
  virtual std::string read() = 0;
  virtual void write(const std::string& data) = 0;
};
class FileDataSource : public DataSource {
 public:
  explicit FileDataSource(std::string path) : path_(std::move(path)) {}
  std::string read() override { return ""; }
  void write(const std::string&) override {}

 private:
  std::string path_;
};
class CompressionDecorator : public DataSource {
 public:
  explicit CompressionDecorator(std::unique_ptr<DataSource> wrapped) : wrapped_(std::move(wrapped)) {}
  std::string read() override { return wrapped_->read(); }
  void write(const std::string& data) override { wrapped_->write(data); }

 private:
  std::unique_ptr<DataSource> wrapped_;
};
class LazyDataSource : public DataSource {
 public:
  explicit LazyDataSource(std::string path) : path_(std::move(path)) {}
  std::string read() override { return load().read(); }
  void write(const std::string& data) override { load().write(data); }

 private:
  FileDataSource& load() {
    if (!real_) real_ = std::make_unique<FileDataSource>(path_);
    return *real_;
  }
  std::string path_;
  std::unique_ptr<FileDataSource> real_;
};
class LegacyStorage {
 public:
  std::string fetchBlob(const std::string& key) { return key; }
  void putBlob(const std::string&, const std::string&) {}
};
class LegacyStorageAdapter : public DataSource {
 public:
  LegacyStorageAdapter(LegacyStorage& storage, std::string key) : storage_(storage), key_(std::move(key)) {}
  std::string read() override { return storage_.fetchBlob(key_); }
  void write(const std::string& data) override { storage_.putBlob(key_, data); }

 private:
  LegacyStorage& storage_;
  std::string key_;
};

class Inventory { public: bool reserve(const std::string&) { return true; } };
class Payments { public: bool charge(double) { return true; } };
class Shipping { public: std::string ship(const std::string&) { return "tracking"; } };
class OrderFacade {
 public:
  std::string placeOrder(const std::string& sku, double amount) {
    inventory_.reserve(sku);
    payments_.charge(amount);
    return shipping_.ship(sku);
  }

 private:
  Inventory inventory_;
  Payments payments_;
  Shipping shipping_;
};

// ---- Chain of Responsibility ----------------------------------------------------
class Handler {
 public:
  virtual ~Handler() = default;
  Handler* setNext(Handler* next) {
    next_ = next;
    return next;
  }
  virtual std::string handle(const std::string& request) { return next_ ? next_->handle(request) : ""; }

 private:
  Handler* next_ = nullptr;
};
class AuthHandler : public Handler {
 public:
  std::string handle(const std::string& request) override {
    return request == "auth" ? "ok" : Handler::handle(request);
  }
};

// ---- Registry-based plugin factory --------------------------------------------
class Plugin {
 public:
  virtual ~Plugin() = default;
  virtual void start() = 0;
};
class PluginRegistry {
 public:
  using Creator = std::function<std::unique_ptr<Plugin>()>;
  static void registerPlugin(const std::string& name, Creator creator) { creators_[name] = std::move(creator); }
  static std::unique_ptr<Plugin> create(const std::string& name) { return creators_.at(name)(); }

 private:
  static std::map<std::string, Creator> creators_;
};

// ---- Iterator ---------------------------------------------------------------
class Range {
 public:
  class Iterator {
   public:
    explicit Iterator(int v) : value_(v) {}
    int operator*() const { return value_; }
    Iterator& operator++() {
      ++value_;
      return *this;
    }
    bool operator!=(const Iterator& o) const { return value_ != o.value_; }

   private:
    int value_;
  };
  Range(int b, int e) : begin_(b), end_(e) {}
  Iterator begin() const { return Iterator(begin_); }
  Iterator end() const { return Iterator(end_); }

 private:
  int begin_;
  int end_;
};

}  // namespace zoo::app
