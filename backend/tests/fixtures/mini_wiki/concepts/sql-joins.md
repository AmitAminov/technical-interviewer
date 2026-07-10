# SQL Joins

**Summary**: SQL joins combine rows from two or more tables based on a related column, and choosing the correct join type is fundamental to writing correct analytical queries.

A join matches rows of one table against rows of another using a predicate,
most commonly equality on a key column. An INNER JOIN keeps only the rows that
match in both tables. A LEFT JOIN keeps every row of the left table and fills
the right side with NULLs where no match exists, which is the usual tool for
"customers with or without orders" style questions. RIGHT JOIN mirrors this,
and FULL OUTER JOIN keeps unmatched rows from both sides. A CROSS JOIN
produces the Cartesian product and is almost always a bug unless a calendar
or grid is being generated deliberately.

## Common pitfalls

Duplicate keys silently multiply rows: joining a table with repeated key
values inflates counts and sums, so aggregating before joining, or using
DISTINCT deliberately, protects downstream metrics. Filtering the right table
of a LEFT JOIN in the WHERE clause quietly converts it into an INNER JOIN;
such filters belong in the ON clause instead. NULL never equals NULL, so keys
containing NULL rows drop out of equality joins entirely.

## Performance considerations

Databases implement joins with nested loops, hash joins, or sort-merge joins,
and the optimizer chooses based on table sizes, indexes, and statistics. An
index on the join column turns a full scan into a lookup, which matters for
large fact tables. Analysts should read the query plan when a join is slow
rather than guessing, and prefer explicit join syntax over comma-separated
tables for readability.

## Related pages

- [[sql-window-functions]]
- [[query-optimization]]
- [[data-cleaning]]
