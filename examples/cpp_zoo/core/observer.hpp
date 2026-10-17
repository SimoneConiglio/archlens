#pragma once
#include <algorithm>
#include <string>
#include <vector>

namespace zoo {

/// Receives events published by a Subject.
class Observer {
 public:
  virtual ~Observer() = default;
  virtual void update(const std::string& event) = 0;
};

/// Keeps a list of observers and notifies them (Observer pattern).
class EventBus {
 public:
  void subscribe(Observer* observer) { observers_.push_back(observer); }
  void unsubscribe(Observer* observer) {
    observers_.erase(std::remove(observers_.begin(), observers_.end(), observer), observers_.end());
  }
  void notifyAll(const std::string& event) {
    for (Observer* o : observers_) o->update(event);
  }

 private:
  std::vector<Observer*> observers_;
};

class AuditLog : public Observer {
 public:
  void update(const std::string& event) override { lines_.push_back(event); }

 private:
  std::vector<std::string> lines_;
};

}  // namespace zoo
