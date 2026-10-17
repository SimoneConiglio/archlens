#pragma once
#include <memory>
#include <vector>

#include "../core/config.hpp"

namespace zoo::shapes {

class ShapeVisitor;

/// Component of the shape tree.
class Shape {
 public:
  virtual ~Shape() = default;
  virtual double area() const = 0;
  virtual void accept(ShapeVisitor& visitor) = 0;
  virtual std::unique_ptr<Shape> clone() const = 0;

 protected:
  Point origin_;
};

class Circle : public Shape {
 public:
  explicit Circle(double radius) : radius_(radius) {}
  double area() const override { return 3.14159 * radius_ * radius_; }
  void accept(ShapeVisitor& visitor) override;
  std::unique_ptr<Shape> clone() const override { return std::make_unique<Circle>(*this); }

 private:
  double radius_;
};

class Square : public Shape {
 public:
  explicit Square(double side) : side_(side) {}
  double area() const override { return side_ * side_; }
  void accept(ShapeVisitor& visitor) override;
  std::unique_ptr<Shape> clone() const override { return std::make_unique<Square>(*this); }

 private:
  double side_;
};

/// Composite: a shape made of shapes.
class Group : public Shape {
 public:
  Group& add(std::unique_ptr<Shape> shape) {
    children_.push_back(std::move(shape));
    return *this;
  }
  double area() const override;
  void accept(ShapeVisitor& visitor) override;
  std::unique_ptr<Shape> clone() const override;

 private:
  std::vector<std::unique_ptr<Shape>> children_;
};

class ShapeVisitor {
 public:
  virtual ~ShapeVisitor() = default;
  virtual void visit(Circle& circle) = 0;
  virtual void visit(Square& square) = 0;
  virtual void visit(Group& group) = 0;
};

class AreaVisitor : public ShapeVisitor {
 public:
  void visit(Circle& circle) override { total_ += circle.area(); }
  void visit(Square& square) override { total_ += square.area(); }
  void visit(Group& group) override { total_ += group.area(); }
  double total() const { return total_; }

 private:
  double total_ = 0;
};

/// Creates shapes by name (simple factory).
class ShapeFactory {
 public:
  std::unique_ptr<Shape> create(const std::string& kind, double size) const;
};

}  // namespace zoo::shapes
